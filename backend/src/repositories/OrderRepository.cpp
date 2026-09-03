#include "repositories/OrderRepository.h"

#include <drogon/drogon.h>

#include <cstdint>
#include <utility>

namespace ticketing
{
namespace
{
void logDatabaseError(const char *operation,
                      const drogon::orm::DrogonDbException &error)
{
    LOG_ERROR << operation << ": " << error.base().what();
}
}  // namespace

void OrderRepository::userExists(
    const drogon::orm::DbClientPtr &client,
    const std::string &userId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    client->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM app_users WHERE id = $1) AS found",
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            onSuccess(rows.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate order user", error);
            onError();
        },
        userId);
}

void OrderRepository::findByIdForUser(
    const drogon::orm::DbClientPtr &client,
    const std::string &orderId,
    const std::string &userId,
    std::function<void(std::optional<TicketOrder>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            ticket_order.id,
            ticket_order.reservation_id,
            session.event_id,
            reservation.session_id,
            item.session_seat_id,
            ticket_order.status,
            ticket_order.total_amount,
            TO_CHAR(
                ticket_order.expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS expires_at,
            TO_CHAR(
                ticket_order.created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS created_at,
            CASE
                WHEN ticket_order.paid_at IS NULL THEN NULL
                ELSE TO_CHAR(
                    ticket_order.paid_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
                )
            END AS paid_at
        FROM orders AS ticket_order
        JOIN reservations AS reservation
            ON reservation.id = ticket_order.reservation_id
        JOIN sessions AS session ON session.id = reservation.session_id
        JOIN reservation_session_seats AS item
            ON item.reservation_id = reservation.id
        WHERE ticket_order.id = $1
          AND ticket_order.user_id = $2
        ORDER BY item.session_seat_id ASC
    )SQL";

    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }

            const auto &first = rows.front();
            TicketOrder order{
                .id = first["id"].as<std::string>(),
                .reservationId =
                    first["reservation_id"].as<std::string>(),
                .eventId = first["event_id"].as<std::string>(),
                .sessionId = first["session_id"].as<std::string>(),
                .seatIds = {},
                .status = first["status"].as<std::string>(),
                .totalAmount = first["total_amount"].as<std::int64_t>(),
                .expiresAt = first["expires_at"].as<std::string>(),
                .createdAt = first["created_at"].as<std::string>(),
                .paidAt = first["paid_at"].isNull()
                              ? std::nullopt
                              : std::optional<std::string>{
                                    first["paid_at"].as<std::string>()},
            };

            order.seatIds.reserve(rows.size());
            for (const auto &row : rows)
            {
                order.seatIds.push_back(
                    row["session_seat_id"].as<std::string>());
            }
            onSuccess(std::move(order));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to find order", error);
            onError();
        },
        orderId,
        userId);
}

void OrderRepository::findExpiredCandidateIds(
    const drogon::orm::DbClientPtr &client,
    std::size_t batchSize,
    std::function<void(std::vector<std::string>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id
        FROM orders
        WHERE status = 'PENDING_PAYMENT'
          AND expires_at <= CURRENT_TIMESTAMP
        ORDER BY expires_at ASC, id ASC
        LIMIT $1
    )SQL";

    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            std::vector<std::string> orderIds;
            orderIds.reserve(rows.size());
            for (const auto &row : rows)
            {
                orderIds.push_back(row["id"].as<std::string>());
            }
            onSuccess(std::move(orderIds));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to scan expired order candidates", error);
            onError();
        },
        static_cast<std::int64_t>(batchSize));
}

void OrderRepository::lockOrderForExpiry(
    const TransactionPtr &transaction,
    const std::string &orderId,
    std::function<void(std::optional<ExpirableOrderRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id,
               user_id,
               reservation_id,
               status,
               total_amount,
               clock_timestamp() >= expires_at AS expired
        FROM orders
        WHERE id = $1
        FOR UPDATE SKIP LOCKED
    )SQL";

    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            const auto &row = rows.front();
            onSuccess(ExpirableOrderRow{
                .id = row["id"].as<std::string>(),
                .userId = row["user_id"].as<std::string>(),
                .reservationId = row["reservation_id"].as<std::string>(),
                .status = row["status"].as<std::string>(),
                .totalAmount = row["total_amount"].as<std::int64_t>(),
                .expired = row["expired"].as<bool>(),
            });
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock order for expiry", error);
            onError();
        },
        orderId);
}

void OrderRepository::lockOrderForUser(
    const TransactionPtr &transaction,
    const std::string &orderId,
    const std::string &userId,
    std::function<void(std::optional<ExpirableOrderRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id,
               user_id,
               reservation_id,
               status,
               total_amount,
               clock_timestamp() >= expires_at AS expired
        FROM orders
        WHERE id = $1 AND user_id = $2
        FOR UPDATE
    )SQL";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty()) { onSuccess(std::nullopt); return; }
            const auto &row = rows.front();
            onSuccess(ExpirableOrderRow{
                .id = row["id"].as<std::string>(),
                .userId = row["user_id"].as<std::string>(),
                .reservationId = row["reservation_id"].as<std::string>(),
                .status = row["status"].as<std::string>(),
                .totalAmount = row["total_amount"].as<std::int64_t>(),
                .expired = row["expired"].as<bool>(),
            });
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock user order", error); onError();
        }, orderId, userId);
}

void OrderRepository::lockOrderForPayment(
    const TransactionPtr &transaction,
    const std::string &orderId,
    std::function<void(std::optional<ExpirableOrderRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id, user_id, reservation_id, status, total_amount,
               clock_timestamp() >= expires_at AS expired
        FROM orders WHERE id = $1 FOR UPDATE
    )SQL";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty()) { onSuccess(std::nullopt); return; }
            const auto &row = rows.front();
            onSuccess(ExpirableOrderRow{
                .id = row["id"].as<std::string>(),
                .userId = row["user_id"].as<std::string>(),
                .reservationId = row["reservation_id"].as<std::string>(),
                .status = row["status"].as<std::string>(),
                .totalAmount = row["total_amount"].as<std::int64_t>(),
                .expired = row["expired"].as<bool>(),
            });
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock payment order", error); onError();
        }, orderId);
}

void OrderRepository::lockReservationForExpiry(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    std::function<void(std::optional<ExpiryReservationRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id, status
        FROM reservations
        WHERE id = $1
        FOR UPDATE
    )SQL";

    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            const auto &row = rows.front();
            onSuccess(ExpiryReservationRow{
                .id = row["id"].as<std::string>(),
                .status = row["status"].as<std::string>(),
            });
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock reservation for expiry", error);
            onError();
        },
        reservationId);
}

void OrderRepository::lockReservationSeatsForExpiry(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    std::function<void(std::vector<ExpirySessionSeatRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT inventory.id,
               inventory.status,
               inventory.current_reservation_id
        FROM reservation_session_seats AS item
        JOIN session_seats AS inventory
          ON inventory.id = item.session_seat_id
        WHERE item.reservation_id = $1
        ORDER BY inventory.id ASC
        FOR UPDATE OF inventory
    )SQL";

    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            std::vector<ExpirySessionSeatRow> seats;
            seats.reserve(rows.size());
            for (const auto &row : rows)
            {
                seats.push_back(ExpirySessionSeatRow{
                    .id = row["id"].as<std::string>(),
                    .status = row["status"].as<std::string>(),
                    .currentReservationId =
                        row["current_reservation_id"].isNull()
                            ? std::nullopt
                            : std::optional<std::string>{
                                  row["current_reservation_id"]
                                      .as<std::string>()},
                });
            }
            onSuccess(std::move(seats));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock reservation seats for expiry",
                             error);
            onError();
        },
        reservationId);
}

void OrderRepository::releaseReservationSeats(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        UPDATE session_seats AS inventory
        SET status = 'AVAILABLE',
            current_reservation_id = NULL
        FROM reservation_session_seats AS item
        WHERE item.reservation_id = $1
          AND item.session_seat_id = inventory.id
          AND inventory.status = 'HELD'
          AND inventory.current_reservation_id = $1
        RETURNING inventory.id
    )SQL";

    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to release reservation seats", error);
            onError();
        },
        reservationId);
}

void OrderRepository::sellReservationSeats(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        UPDATE session_seats AS inventory
        SET status = 'SOLD', current_reservation_id = NULL
        FROM reservation_session_seats AS item
        WHERE item.reservation_id = $1
          AND item.session_seat_id = inventory.id
          AND inventory.status = 'HELD'
          AND inventory.current_reservation_id = $1
        RETURNING inventory.id
    )SQL";
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to sell reservation seats", error); onError();
        }, reservationId);
}

void OrderRepository::expireReservation(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE reservations SET status = 'EXPIRED' "
        "WHERE id = $1 AND status = 'ACTIVE' RETURNING id",
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to expire reservation", error);
            onError();
        },
        reservationId);
}

void OrderRepository::expireOrder(
    const TransactionPtr &transaction,
    const std::string &orderId,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE orders SET status = 'EXPIRED' "
        "WHERE id = $1 AND status = 'PENDING_PAYMENT' RETURNING id",
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to expire order", error);
            onError();
        },
        orderId);
}

void OrderRepository::transitionReservation(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    const std::string &targetStatus,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE reservations SET status = $2 WHERE id = $1 AND status = 'ACTIVE' RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to transition reservation", error); onError();
        }, reservationId, targetStatus);
}

void OrderRepository::transitionOrder(
    const TransactionPtr &transaction,
    const std::string &orderId,
    const std::string &targetStatus,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE orders SET status = $2 WHERE id = $1 AND status = 'PENDING_PAYMENT' RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to transition order", error); onError();
        }, orderId, targetStatus);
}

void OrderRepository::payOrder(
    const TransactionPtr &transaction,
    const std::string &orderId,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "UPDATE orders SET status = 'PAID', paid_at = clock_timestamp() "
        "WHERE id = $1 AND status = 'PENDING_PAYMENT' RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to accept order payment", error); onError();
        }, orderId);
}
}  // namespace ticketing
