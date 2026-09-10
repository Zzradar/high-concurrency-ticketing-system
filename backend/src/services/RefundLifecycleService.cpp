#include "observability/Phase14Metrics.h"
#include "services/RefundLifecycleService.h"
#include "observability/PerformanceMetrics.h"
#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>
#include <set>
namespace ticketing
{
struct RefundLifecycleService::State
{
    std::string id, source, moment;
    RefundTerminalSnapshot snapshot;
    ExpirableOrderRow order;
    OrderRepository::TransactionPtr tx;
    Completion done;
    bool finished{};
    std::size_t count{};
    bool succeeded() const
    {
        return snapshot.refund.mappedState == ProviderRefundState::Succeeded;
    }
};
void RefundLifecycleService::finish(const std::shared_ptr<State> &s, RefundLifecycleOutcome result,
                                    const char *stage)
{
    if (s->finished)
        return;
    s->finished = true;
    if (result == RefundLifecycleOutcome::Completed)
    {
        auto tx = std::move(s->tx);
        tx->setCommitCallback([s](bool ok) {
            auto done = std::move(s->done);
            done(ok ? RefundLifecycleOutcome::Completed : RefundLifecycleOutcome::Failed);
        });
    }
    else
    {
        if (result == RefundLifecycleOutcome::Failed)
            PerformanceMetrics::refundFailure(stage);
        if (result == RefundLifecycleOutcome::Failed)
            LOG_ERROR << "REFUND_INVARIANT stage=" << stage << " refund=" << s->id;
        if (s->tx)
            s->tx->rollback();
        s->tx.reset();
        auto done = std::move(s->done);
        done(result);
    }
}
void RefundLifecycleService::complete(std::string id, RefundTerminalSnapshot snapshot,
                                      Completion done) const
{
    auto s = std::make_shared<State>();
    s->id = std::move(id);
    s->snapshot = std::move(snapshot);
    s->done = std::move(done);
    const auto &r = s->snapshot.refund;
    if (!r.terminal ||
        (r.mappedState != ProviderRefundState::Succeeded &&
         r.mappedState != ProviderRefundState::Failed) ||
        (s->succeeded() ? r.providerStatus != "succeeded"
                        : (r.providerStatus != "failed" && r.providerStatus != "canceled")) ||
        s->snapshot.leaseToken.empty())
        return finish(s, RefundLifecycleOutcome::Failed, "snapshot");
    Phase14Metrics::newTransactionAsync(drogon::app().getDbClient("default"), Phase14Metrics::Flow::Refund,
        [this, s](const OrderRepository::TransactionPtr &tx) {
            if (!tx)
                return finish(s, RefundLifecycleOutcome::Failed);
            s->tx = tx;
            orders_.lockOrderForPayment(
                tx, s->snapshot.orderId,
                [this, s](std::optional<ExpirableOrderRow> order) {
                    if (!order)
                        return finish(s, RefundLifecycleOutcome::Failed, "order");
                    s->order = *order;
                    lockRefund(s);
                },
                [s] { finish(s, RefundLifecycleOutcome::Failed); });
        });
}
void RefundLifecycleService::lockRefund(const std::shared_ptr<State> &s) const
{
    refunds_.lock(
        s->tx, s->id,
        [this, s](const drogon::orm::Result &rows) {
            if (rows.size() != 1)
                return finish(s, RefundLifecycleOutcome::Fenced);
            const auto &row = rows.front();
            const auto &r = s->snapshot.refund;
            if (row["status"].as<std::string>() != "PROCESSING" ||
                row["reconciliation_lease_token"].isNull() ||
                row["reconciliation_lease_token"].as<std::string>() != s->snapshot.leaseToken)
            {
                LOG_INFO << "REFUND_FENCED_BEFORE_RIGHTS refund=" << s->id;
                return finish(s, RefundLifecycleOutcome::Fenced);
            }
            if (row["order_id"].as<std::string>() != s->snapshot.orderId ||
                r.orderId != s->snapshot.orderId || r.localRefundId != s->id ||
                row["payment_attempt_id"].as<std::string>() != s->snapshot.paymentAttemptId ||
                row["provider"].as<std::string>() != r.provider ||
                row["attempt_provider"].as<std::string>() != r.provider ||
                row["amount"].as<std::int64_t>() != r.amount ||
                row["currency"].as<std::string>() != r.currency ||
                row["attempt_currency"].as<std::string>() != r.currency ||
                row["provider_payment_id"].isNull() ||
                row["provider_payment_id"].as<std::string>() != r.providerPaymentId ||
                r.providerRefundId.empty() ||
                (!row["provider_refund_id"].isNull() &&
                 row["provider_refund_id"].as<std::string>() != r.providerRefundId))
                return finish(s, RefundLifecycleOutcome::Failed, "identity");
            s->source = row["source"].as<std::string>();
            if (s->source == "BUYER")
            {
                if (s->order.status != "PAID" || s->order.totalAmount != r.amount ||
                    row["accepted_at"].isNull() ||
                    row["attempt_status"].as<std::string>() != "SUCCEEDED")
                    return finish(s, RefundLifecycleOutcome::Failed, "accepted_order");
                if (s->succeeded())
                    return lockReservation(s);
            }
            else if (s->source != "SYSTEM" || !row["accepted_at"].isNull())
                return finish(s, RefundLifecycleOutcome::Failed, "source");
            terminal(s);
        },
        [s] { finish(s, RefundLifecycleOutcome::Failed); });
}
void RefundLifecycleService::lockReservation(const std::shared_ptr<State> &s) const
{
    s->tx->execSqlAsync(
        "SELECT id,status,user_id FROM reservations WHERE id=$1 FOR UPDATE",
        [this, s](const drogon::orm::Result &r) {
            if (r.size() != 1 || r.front()["status"].as<std::string>() != "CONFIRMED" ||
                r.front()["user_id"].as<std::string>() != s->order.userId)
                return finish(s, RefundLifecycleOutcome::Failed, "reservation");
            // Materialize the complete detail set before locking inventory.
            s->tx->execSqlAsync(
                "SELECT session_seat_id FROM reservation_session_seats WHERE reservation_id=$1 "
                "ORDER BY session_seat_id",
                [this, s](const drogon::orm::Result &items) {
                    std::set<std::string> ids;
                    for (const auto &item : items)
                        ids.insert(item["session_seat_id"].as<std::string>());
                    if (items.empty() || ids.size() != items.size())
                        return finish(s, RefundLifecycleOutcome::Failed, "details");
                    s->count = items.size();
                    lockSeats(s);
                },
                [s](const drogon::orm::DrogonDbException &) {
                    finish(s, RefundLifecycleOutcome::Failed);
                },
                s->order.reservationId);
        },
        [s](const drogon::orm::DrogonDbException &) { finish(s, RefundLifecycleOutcome::Failed); },
        s->order.reservationId);
}
void RefundLifecycleService::lockSeats(const std::shared_ptr<State> &s) const
{
    orders_.lockReservationSeatsForExpiry(
        s->tx, s->order.reservationId,
        [this, s](std::vector<ExpirySessionSeatRow> seats) {
            if (seats.size() != s->count)
                return finish(s, RefundLifecycleOutcome::Failed, "seat_count");
            for (const auto &seat : seats)
                if (seat.status != "SOLD" || seat.currentReservationId)
                    return finish(s, RefundLifecycleOutcome::Failed, "seat_shape");
            ownership(s);
        },
        [s] { finish(s, RefundLifecycleOutcome::Failed); });
}
void RefundLifecycleService::ownership(const std::shared_ptr<State> &s) const
{
    // A fresh READ COMMITTED statement after the ordered seat locks. Legal new
    // reservations must acquire the same rows and observe AVAILABLE before owning them.
    s->tx->execSqlAsync(
        R"SQL(SELECT target.session_seat_id,COUNT(o.id) AS owners,
 COUNT(o.id) FILTER (WHERE r.id=$1 AND o.id=$2) AS target_owners
 FROM reservation_session_seats target
 LEFT JOIN reservation_session_seats item ON item.session_seat_id=target.session_seat_id
 LEFT JOIN reservations r ON r.id=item.reservation_id AND r.status='CONFIRMED'
 LEFT JOIN orders o ON o.reservation_id=r.id AND o.user_id=r.user_id AND o.status='PAID'
 WHERE target.reservation_id=$1 GROUP BY target.session_seat_id)SQL",
        [this, s](const drogon::orm::Result &rows) {
            if (rows.size() != s->count)
                return finish(s, RefundLifecycleOutcome::Failed, "ownership_count");
            for (const auto &row : rows)
                if (row["owners"].as<int>() != 1 || row["target_owners"].as<int>() != 1)
                    return finish(s, RefundLifecycleOutcome::Failed, "ownership_conflict");
            terminal(s);
        },
        [s](const drogon::orm::DrogonDbException &) { finish(s, RefundLifecycleOutcome::Failed); },
        s->order.reservationId, s->order.id);
}
void RefundLifecycleService::terminal(const std::shared_ptr<State> &s) const
{
    s->tx->execSqlAsync(
        "SELECT clock_timestamp()::text AS moment",
        [this, s](const drogon::orm::Result &rows) {
            s->moment = rows.front()["moment"].as<std::string>();
            const auto &r = s->snapshot.refund;
            s->tx->execSqlAsync(
                R"SQL(UPDATE refunds SET provider_refund_id=$2,provider_status=$3,
   status=CASE WHEN $4 THEN 'SUCCEEDED' ELSE 'FAILED' END,
   refunded_at=CASE WHEN $4 THEN $5::timestamptz ELSE NULL END,
   failed_at=CASE WHEN $4 THEN NULL ELSE $5::timestamptz END,
   failure_reason=CASE WHEN $4 THEN NULL ELSE 'PROVIDER_REFUND_FAILED' END,
   provider_terminal_at=$5::timestamptz,provider_last_sync_at=$5::timestamptz,next_reconcile_at=NULL,
   reconciliation_lease_token=NULL,reconciliation_lease_until=NULL
   WHERE id=$1 AND status='PROCESSING' AND reconciliation_lease_token=$6
   AND (provider_refund_id IS NULL OR provider_refund_id=$2) RETURNING id)SQL",
                [this, s](const drogon::orm::Result &updated) {
                    if (updated.size() != 1)
                        return finish(s, RefundLifecycleOutcome::Fenced);
                    if (s->source == "BUYER" && s->succeeded())
                        cancelRights(s);
                    else
                        notify(s);
                },
                [s](const drogon::orm::DrogonDbException &) {
                    finish(s, RefundLifecycleOutcome::Failed, "refund_update");
                },
                s->id, r.providerRefundId, r.providerStatus, s->succeeded(), s->moment,
                s->snapshot.leaseToken);
        },
        [s](const drogon::orm::DrogonDbException &) { finish(s, RefundLifecycleOutcome::Failed); });
}
void RefundLifecycleService::cancelRights(const std::shared_ptr<State> &s) const
{
    orders_.cancelPaidOrderForBuyerRefund(
        s->tx, s->order.id, s->moment,
        [this, s](std::size_t n) {
            if (n != 1)
                return finish(s, RefundLifecycleOutcome::Failed, "order_update");
            orders_.cancelConfirmedReservationForBuyerRefund(
                s->tx, s->order.reservationId,
                [this, s](std::size_t n) {
                    if (n != 1)
                        return finish(s, RefundLifecycleOutcome::Failed, "reservation_update");
                    orders_.releaseSoldSeatsForBuyerRefund(
                        s->tx, s->order.reservationId,
                        [this, s](std::size_t n) {
                            if (n != s->count)
                                return finish(s, RefundLifecycleOutcome::Failed, "seat_update");
                            notify(s);
                        },
                        [s] { finish(s, RefundLifecycleOutcome::Failed, "seat_update"); });
                },
                [s] { finish(s, RefundLifecycleOutcome::Failed, "reservation_update"); });
        },
        [s] { finish(s, RefundLifecycleOutcome::Failed, "order_update"); });
}
void RefundLifecycleService::notify(const std::shared_ptr<State> &s) const
{
    const bool buyer=s->source=="BUYER";
    const std::string type=(buyer?"REFUND_":"AUTO_REFUND_")+std::string(s->succeeded()?"COMPLETED":"FAILED");
    const std::string title=s->succeeded()?"退款已完成":"退款失败";
    const std::string message=s->succeeded()?(buyer?"款项已原路全额退回，订单已取消。":"未被订单接纳的付款已原路全额退回。"):
        (buyer?"退款失败，订单和座位权益仍然有效。当前版本不支持再次自动退款。":"自动退款失败，需要核对渠道状态。");
    const std::string dedupe=buyer?"refund-terminal:"+s->id:
        (s->succeeded()?"auto-refund:":"auto-refund-failed:")+s->snapshot.paymentAttemptId;
    s->tx->execSqlAsync(
        "INSERT INTO user_notifications(id,user_id,order_id,type,title,message,dedupe_key) "
        "VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(dedupe_key) DO NOTHING",
        [s](const drogon::orm::Result &) { finish(s, RefundLifecycleOutcome::Completed); },
        [s](const drogon::orm::DrogonDbException &) { finish(s, RefundLifecycleOutcome::Failed, "notification"); },
        "NTF-"+drogon::utils::getUuid(true), s->order.userId, s->order.id, type,title,message,dedupe);
}
}
