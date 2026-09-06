#include "services/SeatService.h"
#include "observability/PerformanceMetrics.h"

#include <memory>
#include <atomic>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace
{
std::mutex executorMutex;
std::shared_ptr<ticketing::SeatMapComputeExecutor> computeExecutor;
}

namespace ticketing
{
void SeatService::configureComputeExecutor(std::shared_ptr<SeatMapComputeExecutor> executor)
{
    std::lock_guard lock{executorMutex};
    if (!executor || computeExecutor)
        throw std::logic_error("seat map executor must be configured exactly once");
    computeExecutor = std::move(executor);
}

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
    ErrorCallback onError,
    ErrorCallback onBusy) const
{
    auto errorPtr = std::make_shared<ErrorCallback>(std::move(onError));
    std::shared_ptr<SeatMapComputeExecutor> executor;
    {
        std::lock_guard lock{executorMutex};
        executor = computeExecutor;
    }
    if (!executor) { (*errorPtr)(); return; }
    repository_.listBySessionId(
        sessionId,
        [this,
         sessionId,
         checkoutSessionId,
         onSuccess = std::move(onSuccess),
         errorPtr, executor, onBusy = std::move(onBusy)](std::vector<SeatRow> rows) mutable {
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
                     onSuccess = std::move(onSuccess), executor, errorPtr,
                     onBusy = std::move(onBusy),
                     claimed = std::make_shared<std::atomic_bool>(false)](
                        SeatHoldReadResult holds) mutable {
                        // readOwners has a legacy catch/fallback boundary. Do
                        // not allow a thrown submission/completion to resubmit
                        // an already moved request or invoke it twice.
                        if (claimed->exchange(true)) return;
                        try
                        {
                            const bool accepted = executor->trySubmit(
                                [checkoutSessionId, seats = std::move(seats),
                                 holds = std::move(holds),
                                 onSuccess = std::move(onSuccess)]() mutable {
                                    const auto overlayStarted = PerformanceMetrics::seatMapStart();
                                    if (holds.outcome == SeatHoldOutcome::Applied &&
                                        holds.owners.size() == seats.size())
                                    {
                                        for (std::size_t index = 0; index < seats.size(); ++index)
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
                                },
                                [errorPtr] { (*errorPtr)(); });
                            if (!accepted) onBusy();
                        }
                        catch (...)
                        {
                            (*errorPtr)();
                        }
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
