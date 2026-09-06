#pragma once

#include <memory>
#include <chrono>
#include <cstddef>

namespace ticketing
{
class PasswordHashObserver;
class SeatMapComputeObserver;

class PerformanceMetrics final
{
  public:
    enum class SeatMapStage
    {
        DbFetchAndMaterialize, RowBuild, DtoBuild, SeatIdsBuild,
        RedisInputBuild, RedisLookup, OwnerParse, Overlay, JsonBuild,
        ResponseCreate, ResponseCallback,
        LayoutDbFetchAndMaterialize, LayoutJsonBuild,
        AvailabilityDbFetchAndMaterialize, AvailabilityRedisLookup,
        AvailabilityOverlay, AvailabilityJsonBuild,
        Count
    };
    enum class SeatMapRedisOutcome { Success, Timeout, Error, ParseError, Count };
    using TimePoint = std::chrono::steady_clock::time_point;
    static TimePoint seatMapStart();
    static void observeSeatMap(SeatMapStage stage, TimePoint start);
    static void observeSeatMapRedisOutcome(SeatMapRedisOutcome outcome);
    static void registerWithApplication();
    static std::shared_ptr<PasswordHashObserver> passwordHashObserver();
    static std::shared_ptr<SeatMapComputeObserver> seatMapComputeObserver();
};
}  // namespace ticketing
