#include "repositories/CheckoutSessionRepository.h"

#include <drogon/drogon.h>

#include <cstdint>
#include <sstream>
#include <utility>

namespace ticketing
{
namespace
{
constexpr const char *kTimestampFormat =
    "'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'";

std::string placeholders(std::size_t count, std::size_t firstIndex)
{
    std::ostringstream sql;
    for (std::size_t index = 0; index < count; ++index)
    {
        if (index != 0)
        {
            sql << ", ";
        }
        sql << '$' << firstIndex + index;
    }
    return sql.str();
}

void logDatabaseError(const char *operation,
                      const drogon::orm::DrogonDbException &error)
{
    LOG_ERROR << operation << ": " << error.base().what();
}

CheckoutSessionRecord recordFromRow(const drogon::orm::Row &row)
{
    return CheckoutSessionRecord{
        .value = CheckoutSession{
            .id = row["id"].as<std::string>(),
            .userId = row["user_id"].as<std::string>(),
            .sessionId = row["session_id"].as<std::string>(),
            .seatIds = {},
            .status = row["status"].as<std::string>(),
            .revision = row["revision"].as<std::int64_t>(),
            .reservationId = row["reservation_id"].isNull()
                                 ? std::nullopt
                                 : std::optional<std::string>{
                                       row["reservation_id"].as<std::string>()},
            .createdAt = row["created_at"].as<std::string>(),
            .updatedAt = row["updated_at"].as<std::string>(),
            .formalResult = std::nullopt,
        },
        .activeConfirmIdempotencyKey =
            row["active_confirm_idempotency_key"].isNull()
                ? std::nullopt
                : std::optional<std::string>{
                      row["active_confirm_idempotency_key"].as<std::string>()},
    };
}

constexpr const char *kReadColumns = R"SQL(
    checkout.id,
    checkout.user_id,
    checkout.session_id,
    checkout.status,
    checkout.revision,
    checkout.active_confirm_idempotency_key,
    checkout.reservation_id,
    TO_CHAR(
        checkout.created_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    ) AS created_at,
    TO_CHAR(
        checkout.updated_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    ) AS updated_at
)SQL";
}  // namespace

void CheckoutSessionRepository::userExists(
    const TransactionPtr &transaction,
    const std::string &userId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM app_users WHERE id = $1) AS found",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate checkout session user", error);
            onError();
        },
        userId);
}

void CheckoutSessionRepository::findSessionStatus(
    const TransactionPtr &transaction,
    const std::string &sessionId,
    std::function<void(std::optional<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "SELECT status FROM sessions WHERE id = $1",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            onSuccess(rows.front()["status"].as<std::string>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate checkout session Session", error);
            onError();
        },
        sessionId);
}

void CheckoutSessionRepository::findSessionSeatIds(
    const TransactionPtr &transaction,
    const std::string &sessionId,
    const std::vector<std::string> &seatIds,
    std::function<void(std::vector<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "SELECT id FROM session_seats WHERE session_id = $1 AND id IN (" +
        placeholders(seatIds.size(), 2) + ") ORDER BY id ASC";
    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    try
    {
        auto binder = (*transaction) << sql;
        binder << sessionId;
        for (const auto &seatId : seatIds)
        {
            binder << seatId;
        }
        binder >> [onSuccess = std::move(onSuccess)](
                      const drogon::orm::Result &rows) {
            std::vector<std::string> found;
            found.reserve(rows.size());
            for (const auto &row : rows)
            {
                found.push_back(row["id"].as<std::string>());
            }
            onSuccess(std::move(found));
        };
        binder >> [errorPtr](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate checkout session seats", error);
            (*errorPtr)();
        };
        binder.exec();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Failed to bind checkout session seat validation: "
                  << error.what();
        (*errorPtr)();
    }
}

void CheckoutSessionRepository::insertCheckoutSession(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &userId,
    const std::string &sessionId,
    std::function<void(CheckoutSessionRecord)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "INSERT INTO checkout_sessions (id, user_id, session_id, status) "
        "VALUES ($1, $2, $3, 'SELECTING') RETURNING id, user_id, session_id, "
        "status, revision, active_confirm_idempotency_key, reservation_id, "
        "TO_CHAR(created_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS created_at, "
        "TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(recordFromRow(rows.front()));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to create checkout session", error);
            onError();
        },
        checkoutSessionId,
        userId,
        sessionId);
}

void CheckoutSessionRepository::insertSeats(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &sessionId,
    const std::vector<std::string> &seatIds,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    std::ostringstream sql;
    sql << "INSERT INTO checkout_session_seats "
           "(checkout_session_id, session_id, session_seat_id) VALUES ";
    for (std::size_t index = 0; index < seatIds.size(); ++index)
    {
        if (index != 0)
        {
            sql << ", ";
        }
        const auto first = index * 3 + 1;
        sql << "($" << first << ", $" << first + 1 << ", $" << first + 2
            << ')';
    }
    sql << " RETURNING session_seat_id";

    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    try
    {
        auto binder = (*transaction) << sql.str();
        for (const auto &seatId : seatIds)
        {
            binder << checkoutSessionId << sessionId << seatId;
        }
        binder >> [onSuccess = std::move(onSuccess)](
                      const drogon::orm::Result &rows) {
            onSuccess(rows.size());
        };
        binder >> [errorPtr](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to save checkout session seats", error);
            (*errorPtr)();
        };
        binder.exec();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Failed to bind checkout session seats: " << error.what();
        (*errorPtr)();
    }
}

void CheckoutSessionRepository::lockByIdForUser(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &userId,
    std::function<void(std::optional<CheckoutSessionRecord>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kReadColumns} +
                            " FROM checkout_sessions AS checkout "
                            "WHERE checkout.id = $1 AND checkout.user_id = $2 "
                            "FOR UPDATE";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            onSuccess(recordFromRow(rows.front()));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock checkout session", error);
            onError();
        },
        checkoutSessionId,
        userId);
}

void CheckoutSessionRepository::loadSeatIds(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    std::function<void(std::vector<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "SELECT session_seat_id FROM checkout_session_seats "
        "WHERE checkout_session_id = $1 ORDER BY session_seat_id ASC",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            std::vector<std::string> seatIds;
            seatIds.reserve(rows.size());
            for (const auto &row : rows)
            {
                seatIds.push_back(row["session_seat_id"].as<std::string>());
            }
            onSuccess(std::move(seatIds));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to load checkout session seats", error);
            onError();
        },
        checkoutSessionId);
}

void CheckoutSessionRepository::deleteSeats(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    std::function<void()> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "DELETE FROM checkout_session_seats WHERE checkout_session_id = $1",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &) {
            onSuccess();
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to replace checkout session seats", error);
            onError();
        },
        checkoutSessionId);
}

void CheckoutSessionRepository::advanceSeatRevision(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    std::function<void(std::string, std::int64_t)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE checkout_sessions SET updated_at = CURRENT_TIMESTAMP, "
        "revision = revision + 1 "
        "WHERE id = $1 RETURNING TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at, revision";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.front()["updated_at"].as<std::string>(),
                      rows.front()["revision"].as<std::int64_t>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to advance checkout seat revision", error);
            onError();
        },
        checkoutSessionId);
}

void CheckoutSessionRepository::setSubmitting(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &idempotencyKey,
    std::function<void(std::string)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE checkout_sessions SET status = 'SUBMITTING', "
        "active_confirm_idempotency_key = $2, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = $1 AND status = 'SELECTING' "
        "RETURNING TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.front()["updated_at"].as<std::string>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to freeze checkout session", error);
            onError();
        },
        checkoutSessionId,
        idempotencyKey);
}

void CheckoutSessionRepository::setReserved(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &idempotencyKey,
    const std::string &reservationId,
    std::function<void(std::optional<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE checkout_sessions SET status = 'RESERVED', reservation_id = $3, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = $1 AND status = 'SUBMITTING' "
        "AND active_confirm_idempotency_key = $2 "
        "RETURNING TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty()
                          ? std::nullopt
                          : std::optional<std::string>{
                                rows.front()["updated_at"].as<std::string>()});
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to reconcile checkout session", error);
            onError();
        },
        checkoutSessionId,
        idempotencyKey,
        reservationId);
}

void CheckoutSessionRepository::resetSelecting(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    const std::string &idempotencyKey,
    std::function<void(std::optional<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE checkout_sessions SET status = 'SELECTING', "
        "active_confirm_idempotency_key = NULL, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = $1 AND status = 'SUBMITTING' "
        "AND active_confirm_idempotency_key = $2 "
        "RETURNING TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty()
                          ? std::nullopt
                          : std::optional<std::string>{
                                rows.front()["updated_at"].as<std::string>()});
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to reopen checkout session", error);
            onError();
        },
        checkoutSessionId,
        idempotencyKey);
}

void CheckoutSessionRepository::setAbandoned(
    const TransactionPtr &transaction,
    const std::string &checkoutSessionId,
    std::function<void(std::optional<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE checkout_sessions SET status = 'ABANDONED', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = $1 AND status = 'SELECTING' "
        "RETURNING TO_CHAR(updated_at AT TIME ZONE 'UTC', " +
        std::string{kTimestampFormat} + ") AS updated_at";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty()
                          ? std::nullopt
                          : std::optional<std::string>{
                                rows.front()["updated_at"].as<std::string>()});
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to abandon checkout session", error);
            onError();
        },
        checkoutSessionId);
}

void CheckoutSessionRepository::findByIdForUser(
    const drogon::orm::DbClientPtr &client,
    const std::string &checkoutSessionId,
    const std::string &userId,
    std::function<void(std::optional<CheckoutSessionRecord>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "SELECT " + std::string{kReadColumns} +
        ", item.session_seat_id FROM checkout_sessions AS checkout "
        "LEFT JOIN checkout_session_seats AS item "
        "ON item.checkout_session_id = checkout.id "
        "WHERE checkout.id = $1 AND checkout.user_id = $2 "
        "ORDER BY item.session_seat_id ASC";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            auto record = recordFromRow(rows.front());
            for (const auto &row : rows)
            {
                if (!row["session_seat_id"].isNull())
                {
                    record.value.seatIds.push_back(
                        row["session_seat_id"].as<std::string>());
                }
            }
            onSuccess(std::move(record));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to find checkout session", error);
            onError();
        },
        checkoutSessionId,
        userId);
}

void CheckoutSessionRepository::listRecoverable(
    const drogon::orm::DbClientPtr &client,
    const std::string &userId,
    const std::string &sessionId,
    std::function<void(std::vector<CheckoutSessionRecord>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "SELECT " + std::string{kReadColumns} +
        ", item.session_seat_id FROM checkout_sessions AS checkout "
        "LEFT JOIN checkout_session_seats AS item "
        "ON item.checkout_session_id = checkout.id "
        "WHERE checkout.user_id = $1 AND checkout.session_id = $2 "
        "AND checkout.status IN ('SELECTING', 'SUBMITTING') "
        "ORDER BY checkout.created_at DESC, checkout.id ASC, "
        "item.session_seat_id ASC";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            std::vector<CheckoutSessionRecord> records;
            for (const auto &row : rows)
            {
                const auto id = row["id"].as<std::string>();
                if (records.empty() || records.back().value.id != id)
                {
                    records.push_back(recordFromRow(row));
                }
                if (!row["session_seat_id"].isNull())
                {
                    records.back().value.seatIds.push_back(
                        row["session_seat_id"].as<std::string>());
                }
            }
            onSuccess(std::move(records));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to list checkout sessions", error);
            onError();
        },
        userId,
        sessionId);
}

void CheckoutSessionRepository::reconcileSubmitting(
    const drogon::orm::DbClientPtr &client,
    std::size_t batchSize,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        WITH repairable AS (
            SELECT checkout.id,
                   checkout.active_confirm_idempotency_key,
                   reservation.id AS reservation_id
            FROM checkout_sessions AS checkout
            JOIN reservations AS reservation
              ON reservation.user_id = checkout.user_id
             AND reservation.idempotency_key =
                 checkout.active_confirm_idempotency_key
            JOIN orders AS ticket_order
              ON ticket_order.reservation_id = reservation.id
            WHERE checkout.status = 'SUBMITTING'
            ORDER BY checkout.updated_at ASC, checkout.id ASC
            LIMIT $1
        )
        UPDATE checkout_sessions AS checkout
        SET status = 'RESERVED',
            reservation_id = repairable.reservation_id,
            updated_at = CURRENT_TIMESTAMP
        FROM repairable
        WHERE checkout.id = repairable.id
          AND checkout.status = 'SUBMITTING'
          AND checkout.active_confirm_idempotency_key =
              repairable.active_confirm_idempotency_key
        RETURNING checkout.id
    )SQL";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.size());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed startup checkout reconciliation", error);
            onError();
        },
        static_cast<std::int64_t>(batchSize));
}
}  // namespace ticketing
