#pragma once

#include "services/PaymentReconciliationService.h"

#include <cstddef>
#include <memory>

namespace ticketing
{
class PaymentReconciliationWorker
    : public std::enable_shared_from_this<PaymentReconciliationWorker>
{
  public:
    PaymentReconciliationWorker(std::size_t batchSize, double intervalSeconds,
                                double maxBackoffSeconds);
    void start();
  private:
    void runCurrentRound();
    void scheduleNextRound();
    std::size_t batchSize_;
    double intervalSeconds_;
    double maxBackoffSeconds_;
    bool started_{};
    PaymentReconciliationService service_;
};
}  // namespace ticketing
