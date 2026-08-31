#include "services/OrderExpiryService.h"

#include <drogon/drogon.h>

#include <utility>
#include <vector>

namespace ticketing
{
struct OrderExpiryService::BatchState
{
    std::vector<std::string> orderIds;
    std::size_t nextIndex{};
    OrderExpiryRunSummary summary;
    Completion completion;
};

struct OrderExpiryService::ExpireState
{
    std::string orderId;
    std::string reservationId;
    std::size_t expectedSeatCount{};
    OrderRepository::TransactionPtr transaction;
    std::function<void(ExpireOneOutcome)> completion;
    bool finished{false};
};

void OrderExpiryService::runOnce(std::size_t batchSize,
                                 Completion completion) const
{
    auto state = std::make_shared<BatchState>();
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    repository_.findExpiredCandidateIds(
        client,
        batchSize,
        [this, state](std::vector<std::string> orderIds) {
            state->summary.scanned = orderIds.size();
            state->orderIds = std::move(orderIds);
            processNext(state);
        },
        [state] {
            state->summary.failed = 1;
            auto completion = std::move(state->completion);
            completion(state->summary);
        });
}

void OrderExpiryService::processNext(
    const std::shared_ptr<BatchState> &state) const
{
    if (state->nextIndex >= state->orderIds.size())
    {
        auto completion = std::move(state->completion);
        completion(state->summary);
        return;
    }

    auto orderId = state->orderIds[state->nextIndex++];
    expireOne(
        std::move(orderId),
        [this, state](ExpireOneOutcome outcome) {
            switch (outcome)
            {
                case ExpireOneOutcome::Expired:
                    ++state->summary.expired;
                    break;
                case ExpireOneOutcome::Skipped:
                    ++state->summary.skipped;
                    break;
                case ExpireOneOutcome::Failed:
                    ++state->summary.failed;
                    break;
            }
            processNext(state);
        });
}

void OrderExpiryService::expireOne(
    std::string orderId,
    std::function<void(ExpireOneOutcome)> completion) const
{
    auto state = std::make_shared<ExpireState>();
    state->orderId = std::move(orderId);
    state->completion = std::move(completion);

    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const OrderRepository::TransactionPtr &transaction) {
            if (!transaction)
            {
                LOG_ERROR << "Timed out creating order expiry transaction: "
                          << state->orderId;
                failDatabase(state);
                return;
            }
            state->transaction = transaction;
            lockOrder(state);
        });
}

void OrderExpiryService::lockOrder(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.lockOrderForExpiry(
        state->transaction,
        state->orderId,
        [this, state](std::optional<ExpirableOrderRow> order) {
            if (!order || order->status != "PENDING_PAYMENT" ||
                !order->expired)
            {
                skip(state);
                return;
            }
            state->reservationId = std::move(order->reservationId);
            lockReservation(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::lockReservation(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.lockReservationForExpiry(
        state->transaction,
        state->reservationId,
        [this, state](std::optional<ExpiryReservationRow> reservation) {
            if (!reservation)
            {
                failInvariant(state, "reservation is missing");
                return;
            }
            if (reservation->status != "ACTIVE")
            {
                failInvariant(state, "reservation is not ACTIVE");
                return;
            }
            lockSeats(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::lockSeats(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.lockReservationSeatsForExpiry(
        state->transaction,
        state->reservationId,
        [this, state](std::vector<ExpirySessionSeatRow> seats) {
            if (seats.empty())
            {
                failInvariant(state, "reservation has no seat associations");
                return;
            }
            for (const auto &seat : seats)
            {
                if (seat.status != "HELD" || !seat.currentReservationId ||
                    *seat.currentReservationId != state->reservationId)
                {
                    failInvariant(
                        state,
                        "seat status or current reservation ownership mismatch");
                    return;
                }
            }
            state->expectedSeatCount = seats.size();
            releaseSeats(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::releaseSeats(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.releaseReservationSeats(
        state->transaction,
        state->reservationId,
        [this, state](std::size_t released) {
            if (released != state->expectedSeatCount)
            {
                failInvariant(state, "released seat count mismatch");
                return;
            }
            expireReservation(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::expireReservation(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.expireReservation(
        state->transaction,
        state->reservationId,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "reservation transition count mismatch");
                return;
            }
            expireOrder(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::expireOrder(
    const std::shared_ptr<ExpireState> &state) const
{
    repository_.expireOrder(
        state->transaction,
        state->orderId,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                failInvariant(state, "order transition count mismatch");
                return;
            }
            commit(state);
        },
        [state] { failDatabase(state); });
}

void OrderExpiryService::commit(
    const std::shared_ptr<ExpireState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([state](bool committed) {
        if (!committed)
        {
            LOG_ERROR << "Order expiry transaction COMMIT failed: "
                      << state->orderId;
            finish(state, ExpireOneOutcome::Failed);
            return;
        }
        finish(state, ExpireOneOutcome::Expired);
    });
    state->transaction.reset();
    transaction.reset();
}

void OrderExpiryService::skip(const std::shared_ptr<ExpireState> &state)
{
    if (state->transaction)
    {
        state->transaction->rollback();
        state->transaction.reset();
    }
    finish(state, ExpireOneOutcome::Skipped);
}

void OrderExpiryService::failInvariant(
    const std::shared_ptr<ExpireState> &state,
    const char *reason)
{
    LOG_ERROR << "Order expiry invariant failed for " << state->orderId
              << ": " << reason;
    failDatabase(state);
}

void OrderExpiryService::failDatabase(
    const std::shared_ptr<ExpireState> &state)
{
    if (state->transaction)
    {
        state->transaction->rollback();
        state->transaction.reset();
    }
    finish(state, ExpireOneOutcome::Failed);
}

void OrderExpiryService::finish(const std::shared_ptr<ExpireState> &state,
                                ExpireOneOutcome outcome)
{
    if (state->finished)
    {
        return;
    }
    state->finished = true;
    auto completion = std::move(state->completion);
    completion(outcome);
}
}  // namespace ticketing
