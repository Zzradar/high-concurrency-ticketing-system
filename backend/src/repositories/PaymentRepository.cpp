#include "repositories/PaymentRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
namespace
{
constexpr const char *kAttemptColumns = R"SQL(
    attempt.id,
    attempt.order_id,
    attempt.status,
    TO_CHAR(attempt.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS started_at,
    TO_CHAR(attempt.processing_deadline AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS processing_deadline,
    TO_CHAR(attempt.scheduled_complete_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS scheduled_complete_at,
    CASE WHEN attempt.completed_at IS NULL THEN NULL ELSE TO_CHAR(attempt.completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') END AS completed_at,
    CASE WHEN attempt.timed_out_at IS NULL THEN NULL ELSE TO_CHAR(attempt.timed_out_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') END AS timed_out_at,
    CASE WHEN attempt.accepted_at IS NULL THEN NULL ELSE TO_CHAR(attempt.accepted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') END AS accepted_at,
    attempt.failure_reason
)SQL";

void logDatabaseError(const char *operation,
                      const drogon::orm::DrogonDbException &error)
{
    LOG_ERROR << operation << ": " << error.base().what();
}

std::optional<std::string> optionalText(const drogon::orm::Row &row,
                                        const char *column)
{
    return row[column].isNull()
               ? std::nullopt
               : std::optional<std::string>{row[column].as<std::string>()};
}

PaymentAttempt mapAttempt(const drogon::orm::Row &row)
{
    return PaymentAttempt{
        .id = row["id"].as<std::string>(),
        .orderId = row["order_id"].as<std::string>(),
        .status = row["status"].as<std::string>(),
        .startedAt = row["started_at"].as<std::string>(),
        .processingDeadline = row["processing_deadline"].as<std::string>(),
        .scheduledCompleteAt = row["scheduled_complete_at"].as<std::string>(),
        .completedAt = optionalText(row, "completed_at"),
        .timedOutAt = optionalText(row, "timed_out_at"),
        .acceptedAt = optionalText(row, "accepted_at"),
        .failureReason = optionalText(row, "failure_reason"),
    };
}
}  // namespace

void PaymentRepository::findByIdForUser(
    const drogon::orm::DbClientPtr &client,
    const std::string &attemptId,
    const std::string &userId,
    std::function<void(std::optional<PaymentAttempt>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kAttemptColumns} + R"SQL(
        FROM payment_attempts AS attempt
        JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
        WHERE attempt.id = $1 AND ticket_order.user_id = $2
    )SQL";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty() ? std::nullopt
                                   : std::optional<PaymentAttempt>{mapAttempt(rows.front())});
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to find payment attempt", error);
            onError();
        }, attemptId, userId);
}

void PaymentRepository::findLastAcceptedForOrder(
    const drogon::orm::DbClientPtr &client,
    const std::string &orderId,
    std::function<void(std::optional<PaymentAttempt>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kAttemptColumns} + R"SQL(
        FROM payment_attempts AS attempt
        WHERE attempt.order_id = $1 AND attempt.accepted_at IS NOT NULL
        ORDER BY attempt.accepted_at DESC LIMIT 1
    )SQL";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty() ? std::nullopt
                                   : std::optional<PaymentAttempt>{mapAttempt(rows.front())});
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to find accepted payment attempt", error);
            onError();
        }, orderId);
}

void PaymentRepository::lockProcessingForOrder(
    const TransactionPtr &transaction,
    const std::string &orderId,
    std::function<void(std::optional<LockedPaymentAttempt>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kAttemptColumns} + R"SQL(,
        clock_timestamp() >= attempt.processing_deadline AS deadline_passed,
        attempt.started_at < ticket_order.expires_at AS started_before_order_expiry
        FROM payment_attempts AS attempt
        JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
        WHERE attempt.order_id = $1 AND attempt.status = 'PROCESSING'
        FOR UPDATE OF attempt
    )SQL";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty()) { onSuccess(std::nullopt); return; }
            onSuccess(LockedPaymentAttempt{.value = mapAttempt(rows.front()),
                                           .deadlinePassed = rows.front()["deadline_passed"].as<bool>(),
                                           .startedBeforeOrderExpiry = rows.front()["started_before_order_expiry"].as<bool>()});
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock processing payment attempt", error);
            onError();
        }, orderId);
}

void PaymentRepository::lockByIdForOrder(
    const TransactionPtr &transaction,
    const std::string &attemptId,
    const std::string &orderId,
    std::function<void(std::optional<LockedPaymentAttempt>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kAttemptColumns} + R"SQL(,
        clock_timestamp() >= attempt.processing_deadline AS deadline_passed,
        attempt.started_at < ticket_order.expires_at AS started_before_order_expiry
        FROM payment_attempts AS attempt
        JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
        WHERE attempt.id = $1 AND attempt.order_id = $2
        FOR UPDATE OF attempt
    )SQL";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty()) { onSuccess(std::nullopt); return; }
            onSuccess(LockedPaymentAttempt{.value = mapAttempt(rows.front()),
                                           .deadlinePassed = rows.front()["deadline_passed"].as<bool>(),
                                           .startedBeforeOrderExpiry = rows.front()["started_before_order_expiry"].as<bool>()});
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock payment attempt", error);
            onError();
        }, attemptId, orderId);
}

void PaymentRepository::createAttempt(
    const TransactionPtr &transaction,
    const std::string &attemptId,
    const std::string &orderId,
    double delaySeconds,
    double graceSeconds,
    std::function<void(PaymentAttempt)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "WITH moment AS (SELECT clock_timestamp() AS now), "
        "inserted AS (INSERT INTO payment_attempts (id, order_id, status, started_at, "
        "processing_deadline, scheduled_complete_at) "
        "SELECT $1, $2, 'PROCESSING', now, now + ($3 * INTERVAL '1 second'), "
        "now + ($4 * INTERVAL '1 second') FROM moment RETURNING *) SELECT " +
        std::string{kAttemptColumns} + " FROM inserted AS attempt";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(mapAttempt(rows.front()));
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to create payment attempt", error);
            onError();
        }, attemptId, orderId, graceSeconds, delaySeconds);
}

void PaymentRepository::markTimedOut(const TransactionPtr &transaction,
                                     const std::string &attemptId,
                                     std::function<void(std::size_t)> onSuccess,
                                     ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE payment_attempts SET status = 'TIMED_OUT', timed_out_at = clock_timestamp() "
        "WHERE id = $1 AND status = 'PROCESSING' RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to time out payment attempt", error); onError();
        }, attemptId);
}

void PaymentRepository::markFailed(const TransactionPtr &transaction,
                                   const std::string &attemptId,
                                   const std::string &reason,
                                   std::function<void(std::size_t)> onSuccess,
                                   ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE payment_attempts SET status = 'FAILED', completed_at = clock_timestamp(), "
        "accepted_at = NULL, failure_reason = $2 "
        "WHERE id = $1 AND status IN ('PROCESSING', 'TIMED_OUT') RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to fail payment attempt", error); onError();
        }, attemptId, reason);
}

void PaymentRepository::markSucceeded(const TransactionPtr &transaction,
                                      const std::string &attemptId,
                                      bool accepted,
                                      std::function<void(std::size_t)> onSuccess,
                                      ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE payment_attempts SET status = 'SUCCEEDED', completed_at = clock_timestamp(), "
        "accepted_at = CASE WHEN $2 THEN clock_timestamp() ELSE NULL END, failure_reason = NULL "
        "WHERE id = $1 AND status IN ('PROCESSING', 'TIMED_OUT') RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to succeed payment attempt", error); onError();
        }, attemptId, accepted);
}

void PaymentRepository::insertRefund(const TransactionPtr &transaction,
                                     const std::string &refundId,
                                     const std::string &attemptId,
                                     const std::string &orderId,
                                     std::int64_t amount,
                                     const std::string &reason,
                                     std::function<void(std::size_t)> onSuccess,
                                     ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "INSERT INTO refunds (id, payment_attempt_id, order_id, amount, reason, refunded_at) "
        "VALUES ($1, $2, $3, $4, $5, clock_timestamp()) "
        "ON CONFLICT (payment_attempt_id) DO NOTHING RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to create automatic refund", error); onError();
        }, refundId, attemptId, orderId, amount, reason);
}
}  // namespace ticketing
