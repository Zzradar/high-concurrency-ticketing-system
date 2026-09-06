#pragma once

#include <memory>
#include <chrono>
#include <cstddef>

namespace ticketing
{
class PasswordHashObserver;

class PerformanceMetrics final
{
  public:
    enum class SeatMapStage
    {
        DbFetchAndMaterialize, RowBuild, DtoBuild, SeatIdsBuild,
        RedisInputBuild, RedisLookup, OwnerParse, Overlay, JsonBuild,
        ResponseCreate, JsonSerialize, ResponseCallback, Count
    };
    using TimePoint = std::chrono::steady_clock::time_point;
    static TimePoint seatMapStart();
    static void observeSeatMap(SeatMapStage stage, TimePoint start);
    static void observeSeatMapBytes(std::size_t bytes);
    static void registerWithApplication();
    static std::shared_ptr<PasswordHashObserver> passwordHashObserver();
};
}  // namespace ticketing
