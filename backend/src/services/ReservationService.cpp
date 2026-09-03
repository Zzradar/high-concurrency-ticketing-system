#include "services/ReservationService.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <algorithm>
#include <limits>
#include <set>
#include <utility>

namespace ticketing
{
struct ReservationService::FlowState
{
    std::string userId;
    std::string idempotencyKey;
    std::string sessionId;
    std::vector<std::string> seatIds;
    std::string reservationId;
    std::string orderId;
    std::string eventId;
    std::vector<LockedSessionSeatRow> lockedSeats;
    std::int64_t totalAmount{};
    ReservationResult result;
    ReservationRepository::TransactionPtr transaction;
    Completion completion;
    bool finished{false};
};

namespace
{
std::optional<std::pair<std::string, std::vector<std::string>>>
validateAndNormalize(const CreateReservationInput &input)
{
    if (input.userId.empty() || input.idempotencyKey.empty() ||
        input.idempotencyKey.size() > 128 || !input.body.isObject())
    {
        return std::nullopt;
    }

    const auto &session = input.body["sessionId"];
    const auto &seats = input.body["seatIds"];
    if (!session.isString() || session.asString().empty() ||
        !seats.isArray() || seats.size() < 1 || seats.size() > 6)
    {
        return std::nullopt;
    }

    std::vector<std::string> seatIds;
    seatIds.reserve(seats.size());
    std::set<std::string> uniqueSeatIds;
    for (const auto &seat : seats)
    {
        if (!seat.isString() || seat.asString().empty())
        {
            return std::nullopt;
        }
        auto seatId = seat.asString();
        if (!uniqueSeatIds.insert(seatId).second)
        {
            return std::nullopt;
        }
        seatIds.push_back(std::move(seatId));
    }
    std::sort(seatIds.begin(), seatIds.end());
    return std::pair{session.asString(), std::move(seatIds)};
}

bool sameRequest(const ReservationResult &existing,
                 const std::string &sessionId,
                 const std::vector<std::string> &seatIds)
{
    return existing.reservation.sessionId == sessionId &&
           existing.reservation.seatIds == seatIds;
}
}  // namespace

void ReservationService::createReservation(CreateReservationInput input,
                                           Completion completion) const
{
    auto normalized = validateAndNormalize(input);
    if (!normalized)
    {
        completion(CreateReservationResult{
            .outcome = CreateReservationOutcome::InvalidArgument,
            .value = std::nullopt,
        });
        return;
    }

    auto state = std::make_shared<FlowState>();
    state->userId = std::move(input.userId);
    state->idempotencyKey = std::move(input.idempotencyKey);
    state->sessionId = std::move(normalized->first);
    state->seatIds = std::move(normalized->second);
    state->completion = std::move(completion);
    queryExisting(state, false);
}

void ReservationService::createReservationForCheckout(
    std::string userId,
    std::string idempotencyKey,
    std::string sessionId,
    std::vector<std::string> seatIds,
    Completion completion) const
{
    Json::Value body;
    body["sessionId"] = std::move(sessionId);
    body["seatIds"] = Json::Value{Json::arrayValue};
    for (auto &seatId : seatIds)
    {
        body["seatIds"].append(std::move(seatId));
    }
    createReservation(CreateReservationInput{
                          .userId = std::move(userId),
                          .idempotencyKey = std::move(idempotencyKey),
                          .body = std::move(body),
                      },
                      std::move(completion));
}

void ReservationService::queryExisting(
    const std::shared_ptr<FlowState> &state,
    bool required) const
{
    auto client = drogon::app().getDbClient("default");
    repository_.findCompleteByIdempotency(
        client,
        state->userId,
        state->idempotencyKey,
        [this, state, required](
            std::optional<ReservationResult> existing) {
            if (!existing)
            {
                if (required)
                {
                    LOG_ERROR << "Idempotency arbitration completed without "
                                 "a readable Reservation + Order";
                    finish(state,
                           CreateReservationResult{
                               .outcome =
                                   CreateReservationOutcome::InternalError,
                               .value = std::nullopt,
                           });
                    return;
                }
                startTransaction(state);
                return;
            }

            if (!sameRequest(*existing, state->sessionId, state->seatIds))
            {
                finish(state,
                       CreateReservationResult{
                           .outcome = CreateReservationOutcome::
                               IdempotencyConflict,
                           .value = std::nullopt,
                       });
                return;
            }

            finish(state,
                   CreateReservationResult{
                       .outcome = CreateReservationOutcome::Replayed,
                       .value = std::move(existing),
                   });
        },
        [state] {
            finish(state,
                   CreateReservationResult{
                       .outcome = CreateReservationOutcome::InternalError,
                       .value = std::nullopt,
                   });
        });
}

void ReservationService::startTransaction(
    const std::shared_ptr<FlowState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](
            const std::shared_ptr<drogon::orm::Transaction> &transaction) {
            if (!transaction)
            {
                LOG_ERROR << "Timed out creating reservation transaction";
                finish(state,
                       CreateReservationResult{
                           .outcome =
                               CreateReservationOutcome::InternalError,
                           .value = std::nullopt,
                       });
                return;
            }
            state->transaction = transaction;
            validateUser(state);
        });
}

void ReservationService::validateUser(
    const std::shared_ptr<FlowState> &state) const
{
    repository_.userExists(
        state->transaction,
        state->userId,
        [this, state](bool exists) {
            if (!exists)
            {
                fail(state, CreateReservationOutcome::InvalidArgument);
                return;
            }
            validateSession(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::validateSession(
    const std::shared_ptr<FlowState> &state) const
{
    repository_.findSession(
        state->transaction,
        state->sessionId,
        [this, state](std::optional<ReservationSessionRow> session) {
            if (!session)
            {
                fail(state, CreateReservationOutcome::SessionNotFound);
                return;
            }
            if (session->status != "ON_SALE")
            {
                fail(state, CreateReservationOutcome::SessionNotAvailable);
                return;
            }
            state->eventId = std::move(session->eventId);
            arbitrateIdempotency(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::arbitrateIdempotency(
    const std::shared_ptr<FlowState> &state) const
{
    state->reservationId = "RSV-" + drogon::utils::getUuid(true);
    repository_.insertReservation(
        state->transaction,
        state->reservationId,
        state->userId,
        state->sessionId,
        state->idempotencyKey,
        [this, state](std::optional<Reservation> reservation) {
            if (!reservation)
            {
                state->transaction->rollback();
                state->transaction.reset();
                queryExisting(state, true);
                return;
            }
            reservation->seatIds = state->seatIds;
            state->result.reservation = std::move(*reservation);
            lockSeats(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::lockSeats(
    const std::shared_ptr<FlowState> &state) const
{
    repository_.lockSessionSeats(
        state->transaction,
        state->seatIds,
        [this, state](std::vector<LockedSessionSeatRow> seats) {
            if (seats.size() != state->seatIds.size())
            {
                fail(state, CreateReservationOutcome::InvalidArgument);
                return;
            }
            for (const auto &seat : seats)
            {
                if (seat.sessionId != state->sessionId)
                {
                    fail(state, CreateReservationOutcome::InvalidArgument);
                    return;
                }
            }
            for (const auto &seat : seats)
            {
                if (seat.status != "AVAILABLE")
                {
                    fail(state, CreateReservationOutcome::SeatConflict);
                    return;
                }
                if (seat.price >
                    std::numeric_limits<std::int64_t>::max() -
                        state->totalAmount)
                {
                    LOG_ERROR << "Reservation total amount overflow";
                    fail(state, CreateReservationOutcome::InternalError);
                    return;
                }
                state->totalAmount += seat.price;
            }
            state->lockedSeats = std::move(seats);
            holdSeats(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::holdSeats(
    const std::shared_ptr<FlowState> &state) const
{
    repository_.holdSessionSeats(
        state->transaction,
        state->reservationId,
        state->sessionId,
        state->seatIds,
        [this, state](std::size_t updated) {
            if (updated != state->seatIds.size())
            {
                fail(state, CreateReservationOutcome::SeatConflict);
                return;
            }
            insertSeatSnapshots(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::insertSeatSnapshots(
    const std::shared_ptr<FlowState> &state) const
{
    repository_.insertReservationSeats(
        state->transaction,
        state->reservationId,
        state->sessionId,
        state->lockedSeats,
        [this, state](std::size_t inserted) {
            if (inserted != state->seatIds.size())
            {
                LOG_ERROR << "Reservation price snapshot count mismatch";
                fail(state, CreateReservationOutcome::InternalError);
                return;
            }
            createOrder(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::createOrder(
    const std::shared_ptr<FlowState> &state) const
{
    state->orderId = "TKT-" + drogon::utils::getUuid(true);
    repository_.insertOrder(
        state->transaction,
        state->orderId,
        state->reservationId,
        state->totalAmount,
        [this, state](TicketOrder order) {
            order.eventId = state->eventId;
            order.sessionId = state->sessionId;
            order.seatIds = state->seatIds;
            state->result.order = std::move(order);

            if (state->result.reservation.expiresAt !=
                    state->result.order.expiresAt ||
                state->result.reservation.createdAt !=
                    state->result.order.createdAt)
            {
                LOG_ERROR << "Reservation and Order timestamps diverged";
                fail(state, CreateReservationOutcome::InternalError);
                return;
            }
            createOrderNotification(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::createOrderNotification(
    const std::shared_ptr<FlowState> &state) const
{
    notificationRepository_.insert(
        state->transaction,
        "NTF-" + drogon::utils::getUuid(true),
        state->userId,
        state->orderId,
        "ORDER_CREATED",
        "订单已创建",
        "订单已创建，请在有效期内完成支付。",
        "order-created:" + state->orderId,
        [this, state](std::size_t inserted) {
            if (inserted != 1)
            {
                LOG_ERROR << "ORDER_CREATED notification insert mismatch";
                fail(state, CreateReservationOutcome::InternalError);
                return;
            }
            commit(state);
        },
        [state] { fail(state, CreateReservationOutcome::InternalError); });
}

void ReservationService::commit(
    const std::shared_ptr<FlowState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([state](bool committed) {
        if (!committed)
        {
            LOG_ERROR << "Reservation transaction COMMIT failed";
            finish(state,
                   CreateReservationResult{
                       .outcome = CreateReservationOutcome::InternalError,
                       .value = std::nullopt,
                   });
            return;
        }
        finish(state,
               CreateReservationResult{
                   .outcome = CreateReservationOutcome::Created,
                   .value = std::move(state->result),
               });
    });

    state->transaction.reset();
    transaction.reset();
}

void ReservationService::fail(const std::shared_ptr<FlowState> &state,
                              CreateReservationOutcome outcome)
{
    if (state->finished)
    {
        return;
    }
    if (state->transaction)
    {
        state->transaction->rollback();
        state->transaction.reset();
    }
    finish(state,
           CreateReservationResult{
               .outcome = outcome,
               .value = std::nullopt,
           });
}

void ReservationService::finish(const std::shared_ptr<FlowState> &state,
                                CreateReservationResult result)
{
    if (state->finished)
    {
        return;
    }
    state->finished = true;
    auto completion = std::move(state->completion);
    completion(std::move(result));
}
}  // namespace ticketing
