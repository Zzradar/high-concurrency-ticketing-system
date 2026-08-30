#include "repositories/SeatRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
void SeatRepository::listBySessionId(
    const std::string &sessionId,
    std::function<void(std::vector<SeatRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            inventory.id,
            inventory.session_id,
            seat.seat_label,
            seat.row_no,
            seat.seat_no,
            inventory.status,
            seat.zone,
            inventory.price
        FROM session_seats AS inventory
        JOIN seats AS seat ON seat.id = inventory.seat_id
        WHERE inventory.session_id = $1
        ORDER BY seat.row_no ASC,
                 seat.seat_no ASC,
                 inventory.id ASC
    )SQL";

    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            std::vector<SeatRow> seats;
            seats.reserve(result.size());
            for (const auto &row : result)
            {
                seats.push_back(SeatRow{
                    .id = row["id"].as<std::string>(),
                    .sessionId = row["session_id"].as<std::string>(),
                    .label = row["seat_label"].as<std::string>(),
                    .row = row["row_no"].as<std::string>(),
                    .number = row["seat_no"].as<std::int32_t>(),
                    .status = row["status"].as<std::string>(),
                    .zone = row["zone"].as<std::string>(),
                    .price = row["price"].as<std::int64_t>(),
                });
            }
            onSuccess(std::move(seats));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list session seats: "
                      << error.base().what();
            onError();
        },
        sessionId);
}

void SeatRepository::sessionExists(
    const std::string &sessionId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    drogon::app().getDbClient("default")->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM sessions WHERE id = $1) AS found",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            onSuccess(result.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to check session existence: "
                      << error.base().what();
            onError();
        },
        sessionId);
}
}  // namespace ticketing
