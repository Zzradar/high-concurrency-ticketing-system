#include "services/SessionService.h"

#include <memory>
#include <utility>

namespace ticketing
{
TicketSession SessionService::toDto(SessionRow row)
{
    const bool soldOut = row.databaseStatus == "SOLD_OUT" ||
                         row.totalCount == 0 || row.availableCount == 0;

    std::string availability;
    if (soldOut)
    {
        availability = "售罄";
    }
    else if (row.availableCount * 100 <= row.totalCount * 20)
    {
        availability = "紧张";
    }
    else
    {
        availability = "充足";
    }

    return TicketSession{
        .id = std::move(row.id),
        .eventId = std::move(row.eventId),
        .date = std::move(row.date),
        .time = std::move(row.time),
        .weekday = std::move(row.weekday),
        .venue = std::move(row.venue),
        .gateTime = std::move(row.gateTime),
        .status = soldOut ? "SOLD_OUT" : "ON_SALE",
        .priceFrom = row.priceFrom,
        .availability = std::move(availability),
    };
}

void SessionService::listEventSessions(
    const std::string &eventId,
    std::function<void(SessionsResult)> onSuccess,
    ErrorCallback onError) const
{
    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    repository_.listByEventId(
        eventId,
        [this,
         eventId,
         onSuccess = std::move(onSuccess),
         errorPtr](std::vector<SessionRow> rows) mutable {
            if (!rows.empty())
            {
                std::vector<TicketSession> sessions;
                sessions.reserve(rows.size());
                for (auto &row : rows)
                {
                    sessions.push_back(toDto(std::move(row)));
                }
                onSuccess(std::move(sessions));
                return;
            }

            repository_.eventExists(
                eventId,
                [onSuccess = std::move(onSuccess)](bool exists) {
                    if (!exists)
                    {
                        onSuccess(std::nullopt);
                        return;
                    }
                    onSuccess(std::vector<TicketSession>{});
                },
                [errorPtr] { (*errorPtr)(); });
        },
        [errorPtr] { (*errorPtr)(); });
}
}  // namespace ticketing
