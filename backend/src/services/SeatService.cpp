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
    const std::string &checkoutSessionId,
    std::function<void(SeatsResult)> onSuccess,
    ErrorCallback onError) const
{
    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    repository_.listBySessionId(
        sessionId,
        [this,
         sessionId,
         checkoutSessionId,
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
                std::vector<std::string> seatIds;
                seatIds.reserve(seats.size());
                for (const auto &seat : seats)
                {
                    seatIds.push_back(seat.id);
                }
                seatHoldService_.readOwners(
                    sessionId,
                    seatIds,
                    [checkoutSessionId,
                     seats = std::move(seats),
                     onSuccess = std::move(onSuccess)](
                        SeatHoldReadResult holds) mutable {
                        if (holds.outcome == SeatHoldOutcome::Applied &&
                            holds.owners.size() == seats.size())
                        {
                            for (std::size_t index = 0; index < seats.size();
                                 ++index)
                            {
                                if (seats[index].status == "AVAILABLE" &&
                                    holds.owners[index] &&
                                    (checkoutSessionId.empty() ||
                                     *holds.owners[index] != checkoutSessionId))
                                {
                                    seats[index].status = "HELD";
                                }
                            }
                        }
                        onSuccess(std::move(seats));
                    });
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
