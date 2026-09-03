#include "services/OrderLifecycleService.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <utility>

namespace ticketing
{
struct OrderLifecycleService::FlowState
{
    Mode mode{Mode::Expire};
    std::string orderId;
    std::string userId;
    std::string paymentAttemptId;
    ExpirableOrderRow order;
    std::optional<LockedPaymentAttempt> attempt;
    std::string targetStatus;
    std::size_t expectedSeatCount{};
    OrderLifecycleOutcome successOutcome{OrderLifecycleOutcome::Failed};
    bool paymentSucceeded{};
    bool refundRequired{};
    bool paymentResultRecorded{};
    OrderRepository::TransactionPtr transaction;
    Completion completion;
    bool finished{false};
};

void OrderLifecycleService::cancel(std::string orderId,
                                   std::string userId,
                                   Completion completion) const
{
    auto state = std::make_shared<FlowState>();
    state->mode = Mode::Cancel;
    state->orderId = std::move(orderId);
    state->userId = std::move(userId);
    state->completion = std::move(completion);
    start(state);
}

void OrderLifecycleService::expireForWorker(std::string orderId,
                                            Completion completion) const
{
    auto state = std::make_shared<FlowState>();
    state->mode = Mode::Expire;
    state->orderId = std::move(orderId);
    state->completion = std::move(completion);
    start(state);
}

void OrderLifecycleService::completePayment(
    std::string orderId,
    std::string paymentAttemptId,
    bool succeeded,
    Completion completion) const
{
    auto state = std::make_shared<FlowState>();
    state->mode = Mode::PaymentCallback;
    state->orderId = std::move(orderId);
    state->paymentAttemptId = std::move(paymentAttemptId);
    state->paymentSucceeded = succeeded;
    state->successOutcome = OrderLifecycleOutcome::PaymentCompleted;
    state->completion = std::move(completion);
    start(state);
}

void OrderLifecycleService::start(const std::shared_ptr<FlowState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const OrderRepository::TransactionPtr &transaction) {
            if (!transaction)
            {
                LOG_ERROR << "Timed out creating order lifecycle transaction: "
                          << state->orderId;
                finish(state, OrderLifecycleOutcome::Failed, false);
                return;
            }
            state->transaction = transaction;
            lockOrder(state);
        });
}

void OrderLifecycleService::lockOrder(
    const std::shared_ptr<FlowState> &state) const
{
    auto onSuccess = [this, state](std::optional<ExpirableOrderRow> order) {
        inspectOrder(state, std::move(order));
    };
    auto onError = [state] { finish(state, OrderLifecycleOutcome::Failed); };
    if (state->mode == Mode::Cancel)
    {
        orderRepository_.lockOrderForUser(state->transaction,
                                          state->orderId,
                                          state->userId,
                                          std::move(onSuccess),
                                          std::move(onError));
        return;
    }
    if (state->mode == Mode::PaymentCallback)
    {
        orderRepository_.lockOrderForPayment(state->transaction,
                                             state->orderId,
                                             std::move(onSuccess),
                                             std::move(onError));
        return;
    }
    orderRepository_.lockOrderForExpiry(state->transaction,
                                        state->orderId,
                                        std::move(onSuccess),
                                        std::move(onError));
}

void OrderLifecycleService::inspectOrder(
    const std::shared_ptr<FlowState> &state,
    std::optional<ExpirableOrderRow> order) const
{
    if (!order)
    {
        finish(state, state->mode == Mode::Cancel
                          ? OrderLifecycleOutcome::NotFound
                          : OrderLifecycleOutcome::Skipped);
        return;
    }
    state->order = std::move(*order);
    if (state->mode == Mode::PaymentCallback)
    {
        lockCallbackAttempt(state);
        return;
    }
    if (state->mode == Mode::Cancel)
    {
        if (state->order.status == "CANCELLED")
        {
            finish(state, OrderLifecycleOutcome::AlreadyCancelled);
            return;
        }
        if (state->order.status == "EXPIRED")
        {
            finish(state, OrderLifecycleOutcome::OrderExpired);
            return;
        }
        if (state->order.status != "PENDING_PAYMENT")
        {
            finish(state, OrderLifecycleOutcome::NotCancellable);
            return;
        }
    }
    else if (state->order.status != "PENDING_PAYMENT" ||
             !state->order.expired)
    {
        finish(state, OrderLifecycleOutcome::Skipped);
        return;
    }
    lockAttempt(state);
}

void OrderLifecycleService::lockCallbackAttempt(
    const std::shared_ptr<FlowState> &state) const
{
    paymentRepository_.lockByIdForOrder(
        state->transaction,
        state->paymentAttemptId,
        state->orderId,
        [this, state](std::optional<LockedPaymentAttempt> attempt) {
            inspectCallbackAttempt(state, std::move(attempt));
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::inspectCallbackAttempt(
    const std::shared_ptr<FlowState> &state,
    std::optional<LockedPaymentAttempt> attempt) const
{
    if (!attempt)
    {
        failInvariant(state, "payment attempt is missing");
        return;
    }
    state->attempt = std::move(attempt);
    const auto &status = state->attempt->value.status;
    if (status == "SUCCEEDED" || status == "FAILED")
    {
        finish(state, OrderLifecycleOutcome::PaymentCompleted);
        return;
    }
    if (status != "PROCESSING" && status != "TIMED_OUT")
    {
        failInvariant(state, "payment attempt state is not completable");
        return;
    }

    if (state->paymentSucceeded)
    {
        const bool accepted = state->order.status == "PENDING_PAYMENT" &&
                              !state->attempt->deadlinePassed &&
                              state->attempt->startedBeforeOrderExpiry;
        if (accepted)
        {
            state->targetStatus = "PAID";
            lockReservation(state);
            return;
        }
        state->refundRequired = true;
        if (state->order.status == "PENDING_PAYMENT" && state->order.expired)
        {
            state->targetStatus = "EXPIRED";
        }
        mutatePaymentResult(state);
        return;
    }

    if (state->order.status == "PENDING_PAYMENT" && state->order.expired)
    {
        state->targetStatus = "EXPIRED";
    }
    mutatePaymentResult(state);
}

void OrderLifecycleService::lockAttempt(
    const std::shared_ptr<FlowState> &state) const
{
    paymentRepository_.lockProcessingForOrder(
        state->transaction,
        state->orderId,
        [this, state](std::optional<LockedPaymentAttempt> attempt) {
            inspectAttempt(state, std::move(attempt));
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::inspectAttempt(
    const std::shared_ptr<FlowState> &state,
    std::optional<LockedPaymentAttempt> attempt) const
{
    state->attempt = std::move(attempt);
    const bool valid = state->attempt &&
                       !state->attempt->deadlinePassed &&
                       state->attempt->startedBeforeOrderExpiry;
    if (state->attempt && !valid)
    {
        markAttemptTimedOut(state);
        return;
    }
    chooseTerminalTransition(state, valid);
}

void OrderLifecycleService::markAttemptTimedOut(
    const std::shared_ptr<FlowState> &state) const
{
    paymentRepository_.markTimedOut(
        state->transaction,
        state->attempt->value.id,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "payment timeout transition count mismatch");
                return;
            }
            chooseTerminalTransition(state, false);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::chooseTerminalTransition(
    const std::shared_ptr<FlowState> &state,
    bool hasValidProcessing) const
{
    if (state->mode == Mode::Expire && hasValidProcessing)
    {
        finish(state, OrderLifecycleOutcome::Skipped);
        return;
    }

    if (state->mode == Mode::Cancel &&
        (!state->order.expired || hasValidProcessing))
    {
        state->targetStatus = "CANCELLED";
        state->successOutcome = OrderLifecycleOutcome::Cancelled;
    }
    else
    {
        state->targetStatus = "EXPIRED";
        state->successOutcome = state->mode == Mode::Cancel
                                    ? OrderLifecycleOutcome::OrderExpired
                                    : OrderLifecycleOutcome::Expired;
    }
    lockReservation(state);
}

void OrderLifecycleService::lockReservation(
    const std::shared_ptr<FlowState> &state) const
{
    orderRepository_.lockReservationForExpiry(
        state->transaction,
        state->order.reservationId,
        [this, state](std::optional<ExpiryReservationRow> reservation) {
            if (!reservation || reservation->status != "ACTIVE")
            {
                failInvariant(state, "reservation is missing or not ACTIVE");
                return;
            }
            lockSeats(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::lockSeats(
    const std::shared_ptr<FlowState> &state) const
{
    orderRepository_.lockReservationSeatsForExpiry(
        state->transaction,
        state->order.reservationId,
        [this, state](std::vector<ExpirySessionSeatRow> seats) {
            if (seats.empty())
            {
                failInvariant(state, "reservation has no seat associations");
                return;
            }
            for (const auto &seat : seats)
            {
                if (seat.status != "HELD" || !seat.currentReservationId ||
                    *seat.currentReservationId != state->order.reservationId)
                {
                    failInvariant(state, "seat state or ownership mismatch");
                    return;
                }
            }
            state->expectedSeatCount = seats.size();
            if (state->mode == Mode::PaymentCallback &&
                !state->paymentResultRecorded)
                mutatePaymentResult(state);
            else
                continueTerminalTransition(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::mutatePaymentResult(
    const std::shared_ptr<FlowState> &state) const
{
    auto onSuccess = [this, state](std::size_t updated) {
        if (updated != 1)
        {
            failInvariant(state, "payment result transition count mismatch");
            return;
        }
        state->paymentResultRecorded = true;
        afterPaymentResult(state);
    };
    auto onError = [state] { finish(state, OrderLifecycleOutcome::Failed); };
    if (state->paymentSucceeded)
    {
        paymentRepository_.markSucceeded(state->transaction,
                                         state->paymentAttemptId,
                                         state->targetStatus == "PAID",
                                         std::move(onSuccess),
                                         std::move(onError));
    }
    else
    {
        paymentRepository_.markFailed(state->transaction,
                                      state->paymentAttemptId,
                                      "SIMULATED_PAYMENT_FAILURE",
                                      std::move(onSuccess),
                                      std::move(onError));
    }
}

void OrderLifecycleService::afterPaymentResult(
    const std::shared_ptr<FlowState> &state) const
{
    if (state->refundRequired)
    {
        insertRefund(state);
        return;
    }
    if (!state->targetStatus.empty())
    {
        if (state->targetStatus == "EXPIRED")
            checkOtherProcessingBeforeExpiry(state);
        else
            continueTerminalTransition(state);
        return;
    }
    commit(state);
}

void OrderLifecycleService::insertRefund(
    const std::shared_ptr<FlowState> &state) const
{
    std::string reason = "PAYMENT_NOT_ACCEPTED";
    if (state->order.status == "CANCELLED")
        reason = "ORDER_CANCELLED_BEFORE_PAYMENT_CONFIRMATION";
    else if (state->order.status == "EXPIRED")
        reason = "ORDER_EXPIRED_BEFORE_PAYMENT_CONFIRMATION";
    else if (state->order.status == "PAID")
        reason = "DUPLICATE_LATE_PAYMENT";
    paymentRepository_.insertRefund(
        state->transaction,
        "RFD-" + drogon::utils::getUuid(true),
        state->paymentAttemptId,
        state->orderId,
        state->order.totalAmount,
        reason,
        [this, state](std::size_t) { insertRefundNotification(state); },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::insertRefundNotification(
    const std::shared_ptr<FlowState> &state) const
{
    notificationRepository_.insert(
        state->transaction,
        "NTF-" + drogon::utils::getUuid(true),
        state->order.userId,
        state->orderId,
        "AUTO_REFUND_COMPLETED",
        "自动退款已完成",
        "支付结果晚于订单终态到达，款项已原路全额退回。",
        "auto-refund:" + state->paymentAttemptId,
        [this, state](std::size_t) {
            if (!state->targetStatus.empty())
                checkOtherProcessingBeforeExpiry(state);
            else
                commit(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::checkOtherProcessingBeforeExpiry(
    const std::shared_ptr<FlowState> &state) const
{
    paymentRepository_.lockProcessingForOrder(
        state->transaction,
        state->orderId,
        [this, state](std::optional<LockedPaymentAttempt> attempt) {
            inspectOtherProcessingBeforeExpiry(state, std::move(attempt));
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::inspectOtherProcessingBeforeExpiry(
    const std::shared_ptr<FlowState> &state,
    std::optional<LockedPaymentAttempt> attempt) const
{
    if (attempt && !attempt->deadlinePassed &&
        attempt->startedBeforeOrderExpiry)
    {
        state->targetStatus.clear();
        commit(state);
        return;
    }
    if (attempt)
    {
        paymentRepository_.markTimedOut(
            state->transaction,
            attempt->value.id,
            [this, state](std::size_t updated) {
                if (updated != 1)
                {
                    failInvariant(state, "other payment timeout count mismatch");
                    return;
                }
                lockReservation(state);
            },
            [state] { finish(state, OrderLifecycleOutcome::Failed); });
        return;
    }
    lockReservation(state);
}

void OrderLifecycleService::continueTerminalTransition(
    const std::shared_ptr<FlowState> &state) const
{
    if (state->targetStatus == "PAID")
    {
        orderRepository_.sellReservationSeats(
            state->transaction,
            state->order.reservationId,
            [this, state](std::size_t sold) {
                if (sold != state->expectedSeatCount)
                {
                    failInvariant(state, "sold seat count mismatch");
                    return;
                }
                transitionReservation(state);
            },
            [state] { finish(state, OrderLifecycleOutcome::Failed); });
        return;
    }
    releaseSeats(state);
}

void OrderLifecycleService::releaseSeats(
    const std::shared_ptr<FlowState> &state) const
{
    orderRepository_.releaseReservationSeats(
        state->transaction,
        state->order.reservationId,
        [this, state](std::size_t released) {
            if (released != state->expectedSeatCount)
            {
                failInvariant(state, "released seat count mismatch");
                return;
            }
            transitionReservation(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::transitionReservation(
    const std::shared_ptr<FlowState> &state) const
{
    orderRepository_.transitionReservation(
        state->transaction,
        state->order.reservationId,
        state->targetStatus == "PAID" ? "CONFIRMED" : state->targetStatus,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "reservation transition count mismatch");
                return;
            }
            transitionOrder(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::transitionOrder(
    const std::shared_ptr<FlowState> &state) const
{
    auto onSuccess = [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "order transition count mismatch");
                return;
            }
            insertNotification(state);
        };
    auto onError = [state] { finish(state, OrderLifecycleOutcome::Failed); };
    if (state->targetStatus == "PAID")
        orderRepository_.payOrder(state->transaction, state->orderId,
                                  std::move(onSuccess), std::move(onError));
    else
        orderRepository_.transitionOrder(state->transaction, state->orderId,
                                          state->targetStatus,
                                          std::move(onSuccess), std::move(onError));
}

void OrderLifecycleService::insertNotification(
    const std::shared_ptr<FlowState> &state) const
{
    const bool cancelled = state->targetStatus == "CANCELLED";
    const bool paid = state->targetStatus == "PAID";
    notificationRepository_.insert(
        state->transaction,
        "NTF-" + drogon::utils::getUuid(true),
        state->order.userId,
        state->orderId,
        paid ? "PAYMENT_SUCCEEDED" : (cancelled ? "ORDER_CANCELLED" : "ORDER_EXPIRED"),
        paid ? "支付成功" : (cancelled ? "订单已取消" : "订单已过期"),
        paid ? "订单支付成功，座位已确认。"
             : (cancelled ? "订单已取消，所选座位已释放。"
                          : "订单支付时间已结束，所选座位已释放。"),
        std::string{paid ? "payment-succeeded:" :
                    (cancelled ? "order-cancelled:" : "order-expired:")} +
            state->orderId,
        [this, state](std::size_t) { commit(state); },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::commit(
    const std::shared_ptr<FlowState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([state](bool committed) {
        finish(state,
               committed ? state->successOutcome : OrderLifecycleOutcome::Failed,
               false);
    });
    state->transaction.reset();
    transaction.reset();
}

void OrderLifecycleService::finish(const std::shared_ptr<FlowState> &state,
                                   OrderLifecycleOutcome outcome,
                                   bool rollback)
{
    if (state->finished) return;
    state->finished = true;
    if (rollback && state->transaction) state->transaction->rollback();
    state->transaction.reset();
    auto completion = std::move(state->completion);
    completion(outcome);
}

void OrderLifecycleService::failInvariant(
    const std::shared_ptr<FlowState> &state,
    const char *reason)
{
    LOG_ERROR << "Order lifecycle invariant failed for " << state->orderId
              << ": " << reason;
    finish(state, OrderLifecycleOutcome::Failed);
}
}  // namespace ticketing
