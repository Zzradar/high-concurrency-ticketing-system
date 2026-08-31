#pragma once

#include "repositories/OrderRepository.h"

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
    enum class ExpireOneOutcome
    {
        Expired,
        Skipped,
        Failed,
    };

    struct BatchState;
    struct ExpireState;

    void processNext(const std::shared_ptr<BatchState> &state) const;
    void expireOne(std::string orderId,
                   std::function<void(ExpireOneOutcome)> completion) const;
    void lockOrder(const std::shared_ptr<ExpireState> &state) const;
    void lockReservation(const std::shared_ptr<ExpireState> &state) const;
    void lockSeats(const std::shared_ptr<ExpireState> &state) const;
    void releaseSeats(const std::shared_ptr<ExpireState> &state) const;
    void expireReservation(const std::shared_ptr<ExpireState> &state) const;
    void expireOrder(const std::shared_ptr<ExpireState> &state) const;
    void commit(const std::shared_ptr<ExpireState> &state) const;

    static void skip(const std::shared_ptr<ExpireState> &state);
    static void failInvariant(const std::shared_ptr<ExpireState> &state,
                              const char *reason);
    static void failDatabase(const std::shared_ptr<ExpireState> &state);
    static void finish(const std::shared_ptr<ExpireState> &state,
                       ExpireOneOutcome outcome);

    OrderRepository repository_;
};
}  // namespace ticketing
