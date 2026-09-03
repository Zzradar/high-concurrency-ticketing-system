#pragma once

#include "services/OrderLifecycleService.h"

#include <cstddef>
#include <functional>
#include <memory>
#include <string>

namespace ticketing
{
struct OrderExpiryRunSummary
{
    std::size_t scanned{};
    std::size_t expired{};
    std::size_t skipped{};
    std::size_t failed{};
};

class OrderExpiryService
{
  public:
    using Completion = std::function<void(OrderExpiryRunSummary)>;

    void runOnce(std::size_t batchSize, Completion completion) const;

  private:
    struct BatchState;
    void processNext(const std::shared_ptr<BatchState> &state) const;

    OrderRepository repository_;
    OrderLifecycleService lifecycleService_;
};
}  // namespace ticketing
