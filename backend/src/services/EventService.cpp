#include "services/EventService.h"

#include <utility>

namespace ticketing
{
TicketEvent EventService::toDto(EventRow row)
{
    return TicketEvent{
        .id = std::move(row.id),
        .name = std::move(row.name),
        .description = std::move(row.description),
        .city = std::move(row.city),
        .venue = std::move(row.venue),
        .dateRange = std::move(row.dateRange),
        .status = std::move(row.status),
        .cover = std::move(row.cover),
        .sessionCount = row.sessionCount,
        .category = std::move(row.category),
    };
}

void EventService::listEvents(
    std::function<void(std::vector<TicketEvent>)> onSuccess,
    ErrorCallback onError) const
{
    repository_.listEvents(
        [onSuccess = std::move(onSuccess)](std::vector<EventRow> rows) {
            std::vector<TicketEvent> events;
            events.reserve(rows.size());
            for (auto &row : rows)
            {
                events.push_back(toDto(std::move(row)));
            }
            onSuccess(std::move(events));
        },
        std::move(onError));
}

void EventService::getEvent(
    const std::string &eventId,
    std::function<void(std::optional<TicketEvent>)> onSuccess,
    ErrorCallback onError) const
{
    repository_.findEventById(
        eventId,
        [onSuccess = std::move(onSuccess)](std::optional<EventRow> row) {
            if (!row)
            {
                onSuccess(std::nullopt);
                return;
            }
            onSuccess(toDto(std::move(*row)));
        },
        std::move(onError));
}
}  // namespace ticketing
