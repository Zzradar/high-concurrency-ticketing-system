#pragma once

#include "payments/PaymentProvider.h"
#include "repositories/PaymentRepository.h"
#include "services/OrderLifecycleService.h"

#include <cstddef>
#include <functional>
#include <memory>
#include <string>

namespace ticketing
{
struct PaymentReconciliationSummary
{
    std::size_t scanned{};
    std::size_t completed{};
    std::size_t retried{};
    std::size_t failed{};
};

class PaymentReconciliationService
{
  public:
    using Completion = std::function<void(PaymentReconciliationSummary)>;
    void runOnce(std::size_t batchSize, double maxBackoffSeconds,
                 Completion completion) const;

  private:
    struct RunState;
    void processInbox(const std::shared_ptr<RunState> &state) const;
    void claimPayments(const std::shared_ptr<RunState> &state) const;
    void claimRefunds(const std::shared_ptr<RunState> &state) const;
    void processPayment(const std::shared_ptr<RunState> &state,
                        const drogon::orm::Row &row) const;
    void processRefund(const std::shared_ptr<RunState> &state,
                       const drogon::orm::Row &row) const;
    static void finishOne(const std::shared_ptr<RunState> &state);
    static void releaseLease(const std::shared_ptr<RunState> &state,
                             bool payment, const std::string &id);

    PaymentRepository paymentRepository_;
    OrderLifecycleService lifecycleService_;
};
}  // namespace ticketing
