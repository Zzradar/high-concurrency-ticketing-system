#include "services/RefundService.h"
#include "observability/PerformanceMetrics.h"
#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>
namespace ticketing
{
struct RefundService::State
{
    std::string order, user;
    ExpirableOrderRow locked;
    OrderRepository::TransactionPtr tx;
    Completion done;
    bool finished{};
};
void RefundService::finish(const std::shared_ptr<State> &s, RefundResponse result, bool commit)
{
    if (s->finished)
        return;
    s->finished = true;
    if (commit)
    {
        auto tx = std::move(s->tx);
        tx->setCommitCallback([s, result](bool ok) {
            auto done = std::move(s->done);
            PerformanceMetrics::refundRequest(!ok ? "failed"
                                              : result.body["disposition"].asString() == "CREATED"
                                                  ? "created"
                                              : result.status == 202 ? "reused_processing"
                                                                     : "reused_terminal");
            done(ok ? result : RefundResponse{});
        });
    }
    else
    {
        if (s->tx)
            s->tx->rollback();
        s->tx.reset();
        auto done = std::move(s->done);
        PerformanceMetrics::refundRequest(result.status == 409 ? "ineligible" : "failed");
        done(result);
    }
}
void RefundService::request(std::string order, std::string user, Completion done) const
{
    auto s = std::make_shared<State>();
    s->order = std::move(order);
    s->user = std::move(user);
    s->done = std::move(done);
    drogon::app().getDbClient("default")->newTransactionAsync(
        [this, s](const OrderRepository::TransactionPtr &tx) {
            if (!tx)
                return finish(s, {});
            s->tx = tx;
            orders_.lockOrderForPayment(
                tx, s->order,
                [this, s](std::optional<ExpirableOrderRow> order) {
                    if (!order || order->userId != s->user)
                        return finish(s, {404, "ORDER_NOT_FOUND", {}});
                    s->locked = *order;
                    existing(s);
                },
                [s] { finish(s, {}); });
        });
}
void RefundService::existing(const std::shared_ptr<State> &s, bool raced) const
{
    repository_.buyerForOrder(
        s->tx, s->order,
        [this, s, raced](const drogon::orm::Result &rows) {
            if (!rows.empty())
            {
                auto refund = RefundRepository::publicJson(rows.front());
                bool processing = refund["status"].asString() == "PROCESSING";
                Json::Value body;
                body["refund"] = refund;
                body["disposition"] = processing ? "REUSED_PROCESSING" : "REUSED_TERMINAL";
                body["pollAfterMs"] = 2000;
                return finish(s, {processing ? 202 : 200, "", body}, true);
            }
            if (raced)
            {
                LOG_ERROR << "REFUND_ATTEMPT_CONFLICT";
                return finish(s, {});
            }
            eligibility(s);
        },
        [s] { finish(s, {}); });
}
void RefundService::eligibility(const std::shared_ptr<State> &s) const
{
    if (s->locked.status != "PAID")
        return finish(s, {409, "ORDER_NOT_REFUNDABLE", {}});
    s->tx->execSqlAsync(
        "SELECT session.start_time > clock_timestamp() AS eligible FROM orders o JOIN reservations "
        "r ON r.id=o.reservation_id JOIN sessions session ON session.id=r.session_id WHERE o.id=$1",
        [this, s](const drogon::orm::Result &rows) {
            if (rows.size() != 1)
                return finish(s, {});
            if (!rows.front()["eligible"].as<bool>())
                return finish(s, {409, "REFUND_WINDOW_CLOSED", {}});
            repository_.accepted(
                s->tx, s->order,
                [this, s](const drogon::orm::Result &attempts) {
                    if (attempts.size() != 1 || attempts.front()["provider_payment_id"].isNull() ||
                        s->locked.totalAmount <= 0)
                    {
                        LOG_ERROR << "REFUND_ACCEPTED_PAYMENT_INVARIANT";
                        return finish(s, {});
                    }
                    repository_.create(
                        s->tx, "RFD-" + drogon::utils::getUuid(true), s->order,
                        attempts.front()["id"].as<std::string>(),
                        [this, s](const drogon::orm::Result &created) {
                            if (created.empty())
                                return existing(s, true);
                            Json::Value body;
                            body["refund"] = RefundRepository::publicJson(created.front());
                            body["disposition"] = "CREATED";
                            body["pollAfterMs"] = 2000;
                            finish(s, {202, "", body}, true);
                        },
                        [s] { finish(s, {}); });
                },
                [s] { finish(s, {}); });
        },
        [s](const drogon::orm::DrogonDbException &) { finish(s, {}); }, s->order);
}
void RefundService::get(std::string id, std::string user, Completion done) const
{
    repository_.find(
        drogon::app().getDbClient("default"), id, user,
        [done](const drogon::orm::Result &rows) {
            done(rows.empty()
                     ? RefundResponse{404, "REFUND_NOT_FOUND", {}}
                     : RefundResponse{200, "", RefundRepository::publicJson(rows.front())});
        },
        [done] { done({}); });
}
} // namespace ticketing
