#pragma once

#include "services/SeatMapComputeExecutor.h"
#include <drogon/drogon.h>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace ticketing
{
struct SeatAvailabilityConfig
{
    int initLockSeconds{15}, initWaitMilliseconds{1000}, streamMaxlen{10000};
    int deltaScanLimit{1000}, expiryCleanupBatch{512}, ownerCacheTtlSeconds{600};
    int projectionBatchSize{100};
    double projectionIntervalSeconds{0.5}, projectionLeaseSeconds{5};
    static SeatAvailabilityConfig load();
};

class SeatAvailabilityReadModel
{
  public:
    using Reply = std::function<void(const drogon::HttpResponsePtr &)>;
    using Strings = std::vector<std::string>;
    using Result = std::function<void(Strings)>;
    static void configure(std::shared_ptr<SeatMapComputeExecutor> executor);
    static void read(std::string session, std::string zone, std::string owner,
                     std::string generation, std::string since, Reply reply);
    static void apply(std::string session, std::string seat, std::string status,
                      std::string version, Result result);
    static void eval(const std::string &script, const std::string &prefix,
                     Strings args, Result result);
    static std::string prefix(const std::string &session);
    static std::string wrapHold(std::string_view original);
};
} // namespace ticketing
