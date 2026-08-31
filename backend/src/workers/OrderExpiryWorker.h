#pragma once

#include "services/OrderExpiryService.h"

#include <cstddef>
#include <memory>

namespace ticketing
{
class OrderExpiryWorker
    : public std::enable_shared_from_this<OrderExpiryWorker>
{
  public:
    OrderExpiryWorker(std::size_t batchSize, double intervalSeconds);

    void start();

  private:
    void runCurrentRound();
    void scheduleNextRound();

    std::size_t batchSize_;
    double intervalSeconds_;
    bool started_{false};
    OrderExpiryService service_;
};
}  // namespace ticketing
