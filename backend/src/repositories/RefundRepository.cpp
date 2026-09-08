#include "repositories/RefundRepository.h"
#include <drogon/drogon.h>
namespace ticketing
{
namespace
{
const std::string columns = R"SQL(r.*,
 TO_CHAR(r.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_text,
 TO_CHAR(r.refunded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS refunded_text,
 TO_CHAR(r.failed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS failed_text)SQL";
auto failed(RefundRepository::Error error)
{
    return [error](const drogon::orm::DrogonDbException &) {
        LOG_ERROR << "REFUND_DATABASE_ERROR";
        error();
    };
}
} // namespace
Json::Value RefundRepository::publicJson(const drogon::orm::Row &r)
{
    Refund v;
    v.id=r["id"].as<std::string>(); v.orderId=r["order_id"].as<std::string>();
    v.paymentAttemptId=r["payment_attempt_id"].as<std::string>();v.source=r["source"].as<std::string>();
    v.reason=r["reason"].as<std::string>();v.status=r["status"].as<std::string>();
    v.currency=r["currency"].as<std::string>();v.amount=r["amount"].as<std::int64_t>();
    v.createdAt=r["created_text"].as<std::string>();
    if(!r["refunded_text"].isNull())v.refundedAt=r["refunded_text"].as<std::string>();
    if(!r["failed_text"].isNull())v.failedAt=r["failed_text"].as<std::string>();
    return v.toJson();
}
void RefundRepository::find(const drogon::orm::DbClientPtr &c, const std::string &id,
                            const std::string &user, Rows ok, Error err) const
{
    c->execSqlAsync(
        "SELECT " + columns +
            " FROM refunds r JOIN orders o ON o.id=r.order_id WHERE r.id=$1 AND o.user_id=$2",
        ok, failed(err), id, user);
}
void RefundRepository::buyerForOrder(const drogon::orm::DbClientPtr &c, const std::string &id,
                                     Rows ok, Error err) const
{
    c->execSqlAsync("SELECT " + columns +
                        " FROM refunds r WHERE r.order_id=$1 AND r.source='BUYER'",
                    ok, failed(err), id);
}
void RefundRepository::accepted(const drogon::orm::DbClientPtr &c, const std::string &id, Rows ok,
                                Error err) const
{
    c->execSqlAsync("SELECT a.* FROM payment_attempts a WHERE a.order_id=$1 AND "
                    "a.status='SUCCEEDED' AND a.accepted_at IS NOT NULL",
                    ok, failed(err), id);
}
void RefundRepository::create(const drogon::orm::DbClientPtr &c, const std::string &id,
                              const std::string &order, const std::string &attempt, Rows ok,
                              Error err) const
{
    c->execSqlAsync("WITH inserted AS (INSERT INTO refunds "
                    "(id,order_id,payment_attempt_id,amount,currency,provider,source,reason,status,"
                    "next_reconcile_at) "
                    "SELECT "
                    "$1,o.id,a.id,o.total_amount,a.currency,a.provider,'BUYER','BUYER_REQUESTED','"
                    "PROCESSING',clock_timestamp() "
                    "FROM orders o JOIN payment_attempts a ON a.order_id=o.id WHERE o.id=$2 AND "
                    "a.id=$3 AND a.status='SUCCEEDED' AND a.accepted_at IS NOT NULL "
                    "ON CONFLICT DO NOTHING RETURNING *) SELECT " +
                        columns + " FROM inserted r",
                    ok, failed(err), id, order, attempt);
}
void RefundRepository::lock(const drogon::orm::DbClientPtr &c, const std::string &id, Rows ok,
                            Error err) const
{
    c->execSqlAsync("SELECT r.*, a.provider_payment_id, a.provider AS attempt_provider, a.currency "
                    "AS attempt_currency, a.status AS attempt_status, a.accepted_at "
                    "FROM refunds r JOIN payment_attempts a ON a.id=r.payment_attempt_id AND "
                    "a.order_id=r.order_id WHERE r.id=$1 FOR UPDATE OF r",
                    ok, failed(err), id);
}
void RefundRepository::claim(const drogon::orm::DbClientPtr &c, std::size_t batch, double backoff,
                             const std::string &token, Rows ok, Error err) const
{
    c->execSqlAsync(R"SQL(WITH claimed AS (
 SELECT id, CASE WHEN reconciliation_lease_until IS NOT NULL THEN 'lease_expired' ELSE 'retry_due' END AS recovery_reason
 FROM refunds WHERE status='PROCESSING' AND provider_terminal_at IS NULL AND next_reconcile_at <= clock_timestamp()
 AND (reconciliation_lease_until IS NULL OR reconciliation_lease_until <= clock_timestamp())
 ORDER BY next_reconcile_at,id FOR UPDATE SKIP LOCKED LIMIT $1
 ), leased AS (UPDATE refunds r SET provider_retry_count=provider_retry_count+1,
 reconciliation_lease_token=$3,reconciliation_lease_until=clock_timestamp()+INTERVAL '30 seconds',
 next_reconcile_at=clock_timestamp()+LEAST($2,power(2,LEAST(provider_retry_count,5)))*INTERVAL '1 second'
 FROM claimed WHERE r.id=claimed.id RETURNING r.*,claimed.recovery_reason)
 SELECT leased.*,a.provider_payment_id FROM leased JOIN payment_attempts a ON a.id=leased.payment_attempt_id)SQL",
                    ok, failed(err), batch, backoff, token);
}
} // namespace ticketing
