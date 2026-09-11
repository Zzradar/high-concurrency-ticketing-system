#pragma once

#include <memory>
#include <chrono>
#include <cstddef>
#include <string_view>

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
    static void observePaymentProviderRequest(std::string_view provider,
                                              std::string_view operation,
                                              std::string_view outcome);
    static void observePaymentWebhook(std::string_view provider,
                                      std::string_view outcome);
    static void observePaymentReconciliation(std::string_view objectKind,
                                             std::string_view outcome);
    static void setPaymentReconciliationPending(double value);
    static void refundRequest(std::string_view outcome);
    static void refundReconciliation(std::string_view source, std::string_view reason,
                                     std::string_view outcome);
    static void refundConflict(std::string_view reason);
    static void refundFailure(std::string_view stage);
    static void refundAge(double seconds);
    static void availability(std::string_view operation, std::string_view result, double seconds = 0, double seats = 0);
    static void setRefundStatusCount(std::string_view status, double value);
};
}  // namespace ticketing
