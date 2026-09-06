#include "services/SeatService.h"
#include "observability/PerformanceMetrics.h"

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
                const auto dtoStarted = PerformanceMetrics::seatMapStart();
                std::vector<Seat> seats;
                seats.reserve(rows.size());
                for (auto &row : rows)
                {
                    seats.push_back(toDto(std::move(row)));
                }
                PerformanceMetrics::observeSeatMap(
                    PerformanceMetrics::SeatMapStage::DtoBuild, dtoStarted);
                const auto idsStarted = PerformanceMetrics::seatMapStart();
                std::vector<std::string> seatIds;
                seatIds.reserve(seats.size());
                for (const auto &seat : seats)
                {
                    seatIds.push_back(seat.id);
                }
                PerformanceMetrics::observeSeatMap(
                    PerformanceMetrics::SeatMapStage::SeatIdsBuild, idsStarted);
                seatHoldService_.readOwners(
                    sessionId,
                    seatIds,
                    [checkoutSessionId,
                     seats = std::move(seats),
                     onSuccess = std::move(onSuccess)](
                        SeatHoldReadResult holds) mutable {
                        const auto overlayStarted = PerformanceMetrics::seatMapStart();
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
                        PerformanceMetrics::observeSeatMap(
                            PerformanceMetrics::SeatMapStage::Overlay, overlayStarted);
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
