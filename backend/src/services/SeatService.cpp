#include "services/SeatService.h"

#include <memory>
#include <utility>

namespace ticketing
{
Seat SeatService::toDto(SeatRow row)
{
    return Seat{
        .id = std::move(row.id),
        .sessionId = std::move(row.sessionId),
        .label = std::move(row.label),
        .row = std::move(row.row),
        .number = row.number,
        .status = std::move(row.status),
        .zone = std::move(row.zone),
        .price = row.price,
    };
}

void SeatService::listSessionSeats(
    const std::string &sessionId,
    std::function<void(SeatsResult)> onSuccess,
    ErrorCallback onError) const
{
    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    repository_.listBySessionId(
        sessionId,
        [this,
         sessionId,
         onSuccess = std::move(onSuccess),
         errorPtr](std::vector<SeatRow> rows) mutable {
            if (!rows.empty())
            {
                std::vector<Seat> seats;
                seats.reserve(rows.size());
                for (auto &row : rows)
                {
                    seats.push_back(toDto(std::move(row)));
                }
                onSuccess(std::move(seats));
                return;
            }

            repository_.sessionExists(
                sessionId,
                [onSuccess = std::move(onSuccess)](bool exists) {
                    if (!exists)
                    {
                        onSuccess(std::nullopt);
                        return;
                    }
                    onSuccess(std::vector<Seat>{});
                },
                [errorPtr] { (*errorPtr)(); });
        },
        [errorPtr] { (*errorPtr)(); });
}
}  // namespace ticketing
