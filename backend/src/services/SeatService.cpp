#include "services/SeatService.h"
#include "observability/PerformanceMetrics.h"
#include "services/SeatDisplayStatus.h"

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

SeatLayout SeatService::toLayoutDto(SeatLayoutRow row)
{
    return SeatLayout{
        .id = std::move(row.id),
        .label = std::move(row.label),
        .row = std::move(row.row),
        .number = row.number,
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
        [holdService = seatHoldService_, repository = repository_, sessionId,
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
                holdService.readOwners(
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
                                            seats[index].status = displaySeatStatus(
                                                seats[index].status,
                                                holds.owners[index],
                                                checkoutSessionId);
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

            repository.sessionExists(
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

void SeatService::listSeatLayout(
    const std::string &sessionId,
    std::function<void(LayoutResult)> onSuccess,
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

    repository_.listLayoutBySessionId(
        sessionId,
        [sessionId, onSuccess = std::move(onSuccess), errorPtr, executor,
         onBusy = std::move(onBusy), repository = repository_](
            std::vector<SeatLayoutRow> rows) mutable {
            if (!rows.empty())
            {
                try
                {
                    const bool accepted = executor->trySubmit(
                        [rows = std::move(rows),
                         onSuccess = std::move(onSuccess)]() mutable {
                            std::vector<SeatLayout> seats;
                            seats.reserve(rows.size());
                            for (auto &row : rows)
                            {
                                seats.push_back(toLayoutDto(std::move(row)));
                            }
                            onSuccess(std::move(seats));
                        },
                        [errorPtr] { (*errorPtr)(); });
                    if (!accepted) onBusy();
                }
                catch (...)
                {
                    (*errorPtr)();
                }
                return;
            }

            repository.sessionExists(
                sessionId,
                [onSuccess = std::move(onSuccess)](bool exists) mutable {
                    if (!exists) onSuccess(std::nullopt);
                    else onSuccess(std::vector<SeatLayout>{});
                },
                [errorPtr] { (*errorPtr)(); });
        },
        [errorPtr] { (*errorPtr)(); });
}

void SeatService::listSeatAvailability(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    std::function<void(AvailabilityResult)> onSuccess,
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

    repository_.listAvailabilityBySessionId(
        sessionId,
        [sessionId, checkoutSessionId, onSuccess = std::move(onSuccess),
         errorPtr, executor, onBusy = std::move(onBusy),
         repository = repository_, holdService = seatHoldService_](
            std::vector<SeatAvailabilityRow> rows) mutable {
            if (rows.empty())
            {
                repository.sessionExists(
                    sessionId,
                    [onSuccess = std::move(onSuccess)](bool exists) mutable {
                        if (!exists) onSuccess(std::nullopt);
                        else onSuccess(std::vector<SeatAvailability>{});
                    },
                    [errorPtr] { (*errorPtr)(); });
                return;
            }

            std::vector<std::string> seatIds;
            seatIds.reserve(rows.size());
            for (const auto &row : rows) seatIds.push_back(row.id);
            const auto redisStarted = PerformanceMetrics::seatMapStart();
            holdService.readOwners(
                sessionId,
                seatIds,
                [checkoutSessionId, rows = std::move(rows), executor,
                 onSuccess = std::move(onSuccess), errorPtr,
                 onBusy = std::move(onBusy), redisStarted,
                 claimed = std::make_shared<std::atomic_bool>(false)](
                    SeatHoldReadResult holds) mutable {
                    if (claimed->exchange(true)) return;
                    PerformanceMetrics::observeSeatMap(
                        PerformanceMetrics::SeatMapStage::AvailabilityRedisLookup,
                        redisStarted);
                    try
                    {
                        const bool accepted = executor->trySubmit(
                            [checkoutSessionId, rows = std::move(rows),
                             holds = std::move(holds),
                             onSuccess = std::move(onSuccess)]() mutable {
                                const auto overlayStarted =
                                    PerformanceMetrics::seatMapStart();
                                std::vector<SeatAvailability> seats;
                                seats.reserve(rows.size());
                                const bool ownersAligned =
                                    holds.outcome == SeatHoldOutcome::Applied &&
                                    holds.owners.size() == rows.size();
                                for (std::size_t index = 0;
                                     index < rows.size(); ++index)
                                {
                                    const std::optional<std::string> noOwner;
                                    const auto &owner = ownersAligned
                                                            ? holds.owners[index]
                                                            : noOwner;
                                    seats.push_back(SeatAvailability{
                                        .id = std::move(rows[index].id),
                                        .status = displaySeatStatus(
                                            rows[index].status, owner,
                                            checkoutSessionId),
                                    });
                                }
                                PerformanceMetrics::observeSeatMap(
                                    PerformanceMetrics::SeatMapStage::AvailabilityOverlay,
                                    overlayStarted);
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
        },
        [errorPtr] { (*errorPtr)(); });
}
}  // namespace ticketing
