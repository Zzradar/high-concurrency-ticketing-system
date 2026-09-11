#pragma once
#include "services/SeatAvailabilityReadModel.h"
#include <memory>

namespace ticketing
{
class SeatAvailabilityProjectionWorker : public std::enable_shared_from_this<SeatAvailabilityProjectionWorker>
{
  public:
    explicit SeatAvailabilityProjectionWorker(SeatAvailabilityConfig config) : config_(config) {}
    void start();
  private:
    void run();
    void schedule();
    SeatAvailabilityConfig config_;
    bool started_{false};
};
}
