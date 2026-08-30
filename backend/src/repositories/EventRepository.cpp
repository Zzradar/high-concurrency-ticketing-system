#include "repositories/EventRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
namespace
{
constexpr const char *kEventSelect = R"SQL(
    SELECT
        event.id,
        event.name,
        event.description,
        venue.city,
        venue.name AS venue,
        event.date_range,
        event.status,
        event.cover_url,
        COUNT(session.id)::BIGINT AS session_count,
        event.category,
        MIN(session.start_time) AS earliest_session
    FROM events AS event
    JOIN venues AS venue ON venue.id = event.primary_venue_id
    LEFT JOIN sessions AS session ON session.event_id = event.id
)SQL";

constexpr const char *kEventGroupBy = R"SQL(
    GROUP BY
        event.id,
        event.name,
        event.description,
        venue.city,
        venue.name,
        event.date_range,
        event.status,
        event.cover_url,
        event.category
)SQL";

EventRow mapEventRow(const drogon::orm::Row &row)
{
    return EventRow{
        .id = row["id"].as<std::string>(),
        .name = row["name"].as<std::string>(),
        .description = row["description"].as<std::string>(),
        .city = row["city"].as<std::string>(),
        .venue = row["venue"].as<std::string>(),
        .dateRange = row["date_range"].as<std::string>(),
        .status = row["status"].as<std::string>(),
        .cover = row["cover_url"].as<std::string>(),
        .sessionCount = row["session_count"].as<std::int64_t>(),
        .category = row["category"].as<std::string>(),
    };
}
}  // namespace

void EventRepository::listEvents(
    std::function<void(std::vector<EventRow>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = std::string{kEventSelect} + kEventGroupBy +
                            " ORDER BY earliest_session ASC NULLS LAST, event.id ASC";

    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            std::vector<EventRow> events;
            events.reserve(result.size());
            for (const auto &row : result)
            {
                events.push_back(mapEventRow(row));
            }
            onSuccess(std::move(events));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list events: " << error.base().what();
            onError();
        });
}

void EventRepository::findEventById(
    const std::string &eventId,
    std::function<void(std::optional<EventRow>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = std::string{kEventSelect} +
                            " WHERE event.id = $1" + kEventGroupBy;

    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            if (result.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            onSuccess(mapEventRow(result.front()));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to find event: " << error.base().what();
            onError();
        },
        eventId);
}
}  // namespace ticketing
