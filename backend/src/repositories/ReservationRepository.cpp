#include "repositories/ReservationRepository.h"

#include <drogon/drogon.h>

#include <sstream>
#include <utility>

namespace ticketing
{
namespace
{
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
}  // namespace

void ReservationRepository::findCompleteByIdempotency(
    const drogon::orm::DbClientPtr &client,
    const std::string &userId,
    const std::string &idempotencyKey,
    std::function<void(std::optional<ReservationResult>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            reservation.id AS reservation_id,
            reservation.user_id,
            reservation.session_id,
            reservation.status AS reservation_status,
            TO_CHAR(
                reservation.expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS reservation_expires_at,
            TO_CHAR(
                reservation.created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS reservation_created_at,
            ticket_order.id AS order_id,
            ticket_order.status AS order_status,
            ticket_order.total_amount,
            TO_CHAR(
                ticket_order.expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS order_expires_at,
            TO_CHAR(
                ticket_order.created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS order_created_at,
            session.event_id,
            item.session_seat_id
        FROM reservations AS reservation
        JOIN orders AS ticket_order
            ON ticket_order.reservation_id = reservation.id
        JOIN sessions AS session ON session.id = reservation.session_id
        JOIN reservation_session_seats AS item
            ON item.reservation_id = reservation.id
        WHERE reservation.user_id = $1
          AND reservation.idempotency_key = $2
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
            ReservationResult result{
                .reservation = Reservation{
                    .id = first["reservation_id"].as<std::string>(),
                    .userId = first["user_id"].as<std::string>(),
                    .sessionId = first["session_id"].as<std::string>(),
                    .seatIds = {},
                    .status =
                        first["reservation_status"].as<std::string>(),
                    .expiresAt = first["reservation_expires_at"]
                                     .as<std::string>(),
                    .createdAt = first["reservation_created_at"]
                                     .as<std::string>(),
                },
                .order = TicketOrder{
                    .id = first["order_id"].as<std::string>(),
                    .reservationId =
                        first["reservation_id"].as<std::string>(),
                    .eventId = first["event_id"].as<std::string>(),
                    .sessionId = first["session_id"].as<std::string>(),
                    .seatIds = {},
                    .status = first["order_status"].as<std::string>(),
                    .totalAmount =
                        first["total_amount"].as<std::int64_t>(),
                    .expiresAt =
                        first["order_expires_at"].as<std::string>(),
                    .createdAt =
                        first["order_created_at"].as<std::string>(),
                    .paidAt = std::nullopt,
                },
            };

            result.reservation.seatIds.reserve(rows.size());
            result.order.seatIds.reserve(rows.size());
            for (const auto &row : rows)
            {
                auto seatId = row["session_seat_id"].as<std::string>();
                result.reservation.seatIds.push_back(seatId);
                result.order.seatIds.push_back(std::move(seatId));
            }
            onSuccess(std::move(result));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to read idempotent reservation", error);
            onError();
        },
        userId,
        idempotencyKey);
}

void ReservationRepository::userExists(
    const TransactionPtr &transaction,
    const std::string &userId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM app_users WHERE id = $1) AS found",
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            onSuccess(rows.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate reservation user", error);
            onError();
        },
        userId);
}

void ReservationRepository::findSession(
    const TransactionPtr &transaction,
    const std::string &sessionId,
    std::function<void(std::optional<ReservationSessionRow>)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "SELECT event_id, status FROM sessions WHERE id = $1",
        [onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            onSuccess(ReservationSessionRow{
                .eventId = rows.front()["event_id"].as<std::string>(),
                .status = rows.front()["status"].as<std::string>(),
            });
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to validate reservation session", error);
            onError();
        },
        sessionId);
}

void ReservationRepository::insertReservation(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    const std::string &userId,
    const std::string &sessionId,
    const std::string &idempotencyKey,
    std::function<void(std::optional<Reservation>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        INSERT INTO reservations (
            id,
            user_id,
            session_id,
            status,
            expires_at,
            created_at,
            idempotency_key
        )
        VALUES (
            $1,
            $2,
            $3,
            'ACTIVE',
            CURRENT_TIMESTAMP + INTERVAL '15 minutes',
            CURRENT_TIMESTAMP,
            $4
        )
        ON CONFLICT (user_id, idempotency_key)
        DO NOTHING
        RETURNING
            id,
            user_id,
            session_id,
            status,
            TO_CHAR(
                expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS expires_at,
            TO_CHAR(
                created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS created_at
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
            onSuccess(Reservation{
                .id = row["id"].as<std::string>(),
                .userId = row["user_id"].as<std::string>(),
                .sessionId = row["session_id"].as<std::string>(),
                .seatIds = {},
                .status = row["status"].as<std::string>(),
                .expiresAt = row["expires_at"].as<std::string>(),
                .createdAt = row["created_at"].as<std::string>(),
            });
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to arbitrate reservation idempotency",
                             error);
            onError();
        },
        reservationId,
        userId,
        sessionId,
        idempotencyKey);
}

void ReservationRepository::lockSessionSeats(
    const TransactionPtr &transaction,
    const std::vector<std::string> &seatIds,
    std::function<void(std::vector<LockedSessionSeatRow>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "SELECT id, session_id, status, price FROM session_seats "
        "WHERE id IN (" +
        placeholders(seatIds.size(), 1) +
        ") ORDER BY id ASC FOR UPDATE";

    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    try
    {
        auto binder = (*transaction) << sql;
        for (const auto &seatId : seatIds)
        {
            binder << seatId;
        }
        binder >> [onSuccess = std::move(onSuccess)](
                      const drogon::orm::Result &rows) {
            std::vector<LockedSessionSeatRow> seats;
            seats.reserve(rows.size());
            for (const auto &row : rows)
            {
                seats.push_back(LockedSessionSeatRow{
                    .id = row["id"].as<std::string>(),
                    .sessionId = row["session_id"].as<std::string>(),
                    .status = row["status"].as<std::string>(),
                    .price = row["price"].as<std::int64_t>(),
                });
            }
            onSuccess(std::move(seats));
        };
        binder >> [errorPtr](
                      const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to lock reservation seats", error);
            (*errorPtr)();
        };
        binder.exec();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Failed to bind reservation seat locks: "
                  << error.what();
        (*errorPtr)();
    }
}

void ReservationRepository::holdSessionSeats(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    const std::string &sessionId,
    const std::vector<std::string> &seatIds,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql =
        "UPDATE session_seats SET status = 'HELD', "
        "current_reservation_id = $1 "
        "WHERE session_id = $2 AND status = 'AVAILABLE' AND id IN (" +
        placeholders(seatIds.size(), 3) + ") RETURNING id";

    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    try
    {
        auto binder = (*transaction) << sql;
        binder << reservationId << sessionId;
        for (const auto &seatId : seatIds)
        {
            binder << seatId;
        }
        binder >> [onSuccess = std::move(onSuccess)](
                      const drogon::orm::Result &rows) {
            onSuccess(rows.size());
        };
        binder >> [errorPtr](
                      const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to hold reservation seats", error);
            (*errorPtr)();
        };
        binder.exec();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Failed to bind reservation seat update: "
                  << error.what();
        (*errorPtr)();
    }
}

void ReservationRepository::insertReservationSeats(
    const TransactionPtr &transaction,
    const std::string &reservationId,
    const std::string &sessionId,
    const std::vector<LockedSessionSeatRow> &seats,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    std::ostringstream sql;
    sql << "INSERT INTO reservation_session_seats "
           "(reservation_id, session_id, session_seat_id, reserved_price) "
           "VALUES ";
    for (std::size_t index = 0; index < seats.size(); ++index)
    {
        if (index != 0)
        {
            sql << ", ";
        }
        const auto first = index * 4 + 1;
        sql << "($" << first << ", $" << first + 1 << ", $"
            << first + 2 << ", $" << first + 3 << ')';
    }
    sql << " RETURNING session_seat_id";

    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    try
    {
        auto binder = (*transaction) << sql.str();
        for (const auto &seat : seats)
        {
            binder << reservationId << sessionId << seat.id << seat.price;
        }
        binder >> [onSuccess = std::move(onSuccess)](
                      const drogon::orm::Result &rows) {
            onSuccess(rows.size());
        };
        binder >> [errorPtr](
                      const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to snapshot reservation seat prices",
                             error);
            (*errorPtr)();
        };
        binder.exec();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Failed to bind reservation seat snapshots: "
                  << error.what();
        (*errorPtr)();
    }
}

void ReservationRepository::insertOrder(
    const TransactionPtr &transaction,
    const std::string &orderId,
    const std::string &reservationId,
    std::int64_t totalAmount,
    std::function<void(TicketOrder)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        INSERT INTO orders (
            id,
            user_id,
            reservation_id,
            status,
            total_amount,
            expires_at,
            created_at
        )
        SELECT
            $1,
            reservation.user_id,
            reservation.id,
            'PENDING_PAYMENT',
            $2,
            reservation.expires_at,
            reservation.created_at
        FROM reservations AS reservation
        WHERE reservation.id = $3
        RETURNING
            id,
            reservation_id,
            status,
            total_amount,
            TO_CHAR(
                expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS expires_at,
            TO_CHAR(
                created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
            ) AS created_at
    )SQL";

    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    transaction->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess), errorPtr](
            const drogon::orm::Result &rows) {
            if (rows.size() != 1)
            {
                LOG_ERROR << "Order INSERT did not return exactly one row";
                (*errorPtr)();
                return;
            }
            const auto &row = rows.front();
            onSuccess(TicketOrder{
                .id = row["id"].as<std::string>(),
                .reservationId =
                    row["reservation_id"].as<std::string>(),
                .eventId = {},
                .sessionId = {},
                .seatIds = {},
                .status = row["status"].as<std::string>(),
                .totalAmount = row["total_amount"].as<std::int64_t>(),
                .expiresAt = row["expires_at"].as<std::string>(),
                .createdAt = row["created_at"].as<std::string>(),
                .paidAt = std::nullopt,
            });
        },
        [errorPtr](
            const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to create reservation order", error);
            (*errorPtr)();
        },
        orderId,
        totalAmount,
        reservationId);
}
}  // namespace ticketing
