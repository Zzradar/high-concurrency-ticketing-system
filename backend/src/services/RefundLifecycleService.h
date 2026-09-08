#pragma once
#include "payments/PaymentProvider.h"
#include "repositories/OrderRepository.h"
#include "repositories/RefundRepository.h"
namespace ticketing
{
struct RefundTerminalSnapshot
{
    std::string orderId, paymentAttemptId;
    ProviderRefund refund;
    std::string leaseToken;
};
enum class RefundLifecycleOutcome
{
    Completed,
    Fenced,
    Failed
};
class RefundLifecycleService
{
  public:
    using Completion = std::function<void(RefundLifecycleOutcome)>;
    void complete(std::string id, RefundTerminalSnapshot, Completion) const;

  private:
    struct State;
    void lockRefund(const std::shared_ptr<State> &) const;
    void lockReservation(const std::shared_ptr<State> &) const;
    void lockSeats(const std::shared_ptr<State> &) const;
    void ownership(const std::shared_ptr<State> &) const;
    void terminal(const std::shared_ptr<State> &) const;
    void cancelRights(const std::shared_ptr<State> &) const;
    void notify(const std::shared_ptr<State> &) const;
    static void finish(const std::shared_ptr<State> &, RefundLifecycleOutcome,
                       const char *stage = "database");
    OrderRepository orders_;
    RefundRepository refunds_;
};
} // namespace ticketing
