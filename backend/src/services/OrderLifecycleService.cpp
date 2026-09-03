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
    ExpirableOrderRow order;
    std::optional<LockedPaymentAttempt> attempt;
    std::string targetStatus;
    std::size_t expectedSeatCount{};
    OrderLifecycleOutcome successOutcome{OrderLifecycleOutcome::Failed};
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
            releaseSeats(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
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
        state->targetStatus,
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
    orderRepository_.transitionOrder(
        state->transaction,
        state->orderId,
        state->targetStatus,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "order transition count mismatch");
                return;
            }
            insertNotification(state);
        },
        [state] { finish(state, OrderLifecycleOutcome::Failed); });
}

void OrderLifecycleService::insertNotification(
    const std::shared_ptr<FlowState> &state) const
{
    const bool cancelled = state->targetStatus == "CANCELLED";
    notificationRepository_.insert(
        state->transaction,
        "NTF-" + drogon::utils::getUuid(true),
        state->order.userId,
        state->orderId,
        cancelled ? "ORDER_CANCELLED" : "ORDER_EXPIRED",
        cancelled ? "订单已取消" : "订单已过期",
        cancelled ? "订单已取消，所选座位已释放。"
                  : "订单支付时间已结束，所选座位已释放。",
        std::string{cancelled ? "order-cancelled:" : "order-expired:"} +
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
