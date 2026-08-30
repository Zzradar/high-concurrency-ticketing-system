#include "repositories/SessionRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
void SessionRepository::listByEventId(
    const std::string &eventId,
    std::function<void(std::vector<SessionRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            session.id,
            session.event_id,
            TO_CHAR(
                session.start_time AT TIME ZONE 'Asia/Shanghai',
                'MM"月"DD"日"'
            ) AS date,
            TO_CHAR(
                session.start_time AT TIME ZONE 'Asia/Shanghai',
                'HH24:MI'
            ) AS time,
            CASE EXTRACT(
                ISODOW FROM session.start_time AT TIME ZONE 'Asia/Shanghai'
            )::INTEGER
                WHEN 1 THEN '周一'
                WHEN 2 THEN '周二'
                WHEN 3 THEN '周三'
                WHEN 4 THEN '周四'
                WHEN 5 THEN '周五'
                WHEN 6 THEN '周六'
                WHEN 7 THEN '周日'
            END AS weekday,
            venue.name || ' · ' || session.hall_name AS venue,
            TO_CHAR(
                session.gate_time AT TIME ZONE 'Asia/Shanghai',
                'HH24:MI'
            ) AS gate_time,
            session.status AS database_status,
            COALESCE(MIN(inventory.price), 0)::BIGINT AS price_from,
            COUNT(inventory.id)::BIGINT AS total_count,
            COUNT(inventory.id) FILTER (
                WHERE inventory.status = 'AVAILABLE'
            )::BIGINT AS available_count
        FROM sessions AS session
        JOIN venues AS venue ON venue.id = session.venue_id
        LEFT JOIN session_seats AS inventory
            ON inventory.session_id = session.id
        WHERE session.event_id = $1
        GROUP BY
            session.id,
            session.event_id,
            session.start_time,
            session.gate_time,
            session.hall_name,
            session.status,
            venue.name
        ORDER BY session.start_time ASC, session.id ASC
    )SQL";

    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            std::vector<SessionRow> sessions;
            sessions.reserve(result.size());
            for (const auto &row : result)
            {
                sessions.push_back(SessionRow{
                    .id = row["id"].as<std::string>(),
                    .eventId = row["event_id"].as<std::string>(),
                    .date = row["date"].as<std::string>(),
                    .time = row["time"].as<std::string>(),
                    .weekday = row["weekday"].as<std::string>(),
                    .venue = row["venue"].as<std::string>(),
                    .gateTime = row["gate_time"].as<std::string>(),
                    .databaseStatus =
                        row["database_status"].as<std::string>(),
                    .priceFrom = row["price_from"].as<std::int64_t>(),
                    .totalCount = row["total_count"].as<std::int64_t>(),
                    .availableCount =
                        row["available_count"].as<std::int64_t>(),
                });
            }
            onSuccess(std::move(sessions));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list event sessions: "
                      << error.base().what();
            onError();
        },
        eventId);
}

void SessionRepository::eventExists(
    const std::string &eventId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    drogon::app().getDbClient("default")->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM events WHERE id = $1) AS found",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            onSuccess(result.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to check event existence: "
                      << error.base().what();
            onError();
        },
        eventId);
}
}  // namespace ticketing
