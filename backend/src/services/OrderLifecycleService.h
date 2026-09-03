#pragma once

#include "repositories/NotificationRepository.h"
#include "repositories/OrderRepository.h"
#include "repositories/PaymentRepository.h"

#include <functional>
#include <memory>
#include <string>

namespace ticketing
{
enum class OrderLifecycleOutcome
{
    Cancelled,
    Expired,
    AlreadyCancelled,
    OrderExpired,
    NotFound,
    NotCancellable,
    Skipped,
    Failed,
};

class OrderLifecycleService
{
  public:
    using Completion = std::function<void(OrderLifecycleOutcome)>;

    void cancel(std::string orderId,
                std::string userId,
                Completion completion) const;
    void expireForWorker(std::string orderId, Completion completion) const;

  private:
    enum class Mode { Cancel, Expire };
    struct FlowState;

    void start(const std::shared_ptr<FlowState> &state) const;
    void lockOrder(const std::shared_ptr<FlowState> &state) const;
    void inspectOrder(const std::shared_ptr<FlowState> &state,
                      std::optional<ExpirableOrderRow> order) const;
    void lockAttempt(const std::shared_ptr<FlowState> &state) const;
    void inspectAttempt(
        const std::shared_ptr<FlowState> &state,
        std::optional<LockedPaymentAttempt> attempt) const;
    void markAttemptTimedOut(const std::shared_ptr<FlowState> &state) const;
    void chooseTerminalTransition(const std::shared_ptr<FlowState> &state,
                                  bool hasValidProcessing) const;
    void lockReservation(const std::shared_ptr<FlowState> &state) const;
    void lockSeats(const std::shared_ptr<FlowState> &state) const;
    void releaseSeats(const std::shared_ptr<FlowState> &state) const;
    void transitionReservation(const std::shared_ptr<FlowState> &state) const;
    void transitionOrder(const std::shared_ptr<FlowState> &state) const;
    void insertNotification(const std::shared_ptr<FlowState> &state) const;
    void commit(const std::shared_ptr<FlowState> &state) const;

    static void finish(const std::shared_ptr<FlowState> &state,
                       OrderLifecycleOutcome outcome,
                       bool rollback = true);
    static void failInvariant(const std::shared_ptr<FlowState> &state,
                              const char *reason);

    OrderRepository orderRepository_;
    PaymentRepository paymentRepository_;
    NotificationRepository notificationRepository_;
};
}  // namespace ticketing
