#include "services/CheckoutSessionService.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <algorithm>
#include <iterator>
#include <limits>
#include <set>
#include <utility>

namespace ticketing
{
struct CheckoutSessionService::CreateState
{
    std::string checkoutSessionId;
    std::string userId;
    std::string sessionId;
    std::vector<std::string> seatIds;
    CheckoutSessionRecord record;
    CheckoutSessionRepository::TransactionPtr transaction;
    Completion completion;
    bool redisPrepareAttempted{false};
    bool finished{false};
};

struct CheckoutSessionService::ReplaceState
{
    std::string checkoutSessionId;
    std::string userId;
    std::vector<std::string> seatIds;
    std::vector<std::string> oldSeatIds;
    std::vector<std::string> addedSeatIds;
    std::vector<std::string> retainedSeatIds;
    std::vector<std::string> removedSeatIds;
    std::int64_t expectedRevision{};
    std::int64_t targetRevision{};
    CheckoutSessionRecord record;
    CheckoutSessionRepository::TransactionPtr transaction;
    Completion completion;
    bool redisPrepareAttempted{false};
    bool finished{false};
};

struct CheckoutSessionService::ConfirmState
{
    std::string checkoutSessionId;
    std::string userId;
    std::string idempotencyKey;
    CheckoutSessionRecord record;
    ReservationResult formalResult;
    CheckoutSessionOutcome businessFailure{
        CheckoutSessionOutcome::InternalError};
    CheckoutSessionRepository::TransactionPtr transaction;
    Completion completion;
    bool finished{false};
};

struct CheckoutSessionService::ResolveState
{
    CheckoutSessionRecord record;
    ReservationResult formalResult;
    CheckoutSessionOutcome successOutcome{CheckoutSessionOutcome::Found};
    CheckoutSessionRepository::TransactionPtr transaction;
    Completion completion;
    bool finished{false};
};

struct CheckoutSessionService::AbandonState
{
    std::string checkoutSessionId;
    std::string userId;
    CheckoutSessionRecord record;
    CheckoutSessionRepository::TransactionPtr transaction;
    Completion completion;
    bool finished{false};
};

namespace
{
std::optional<std::vector<std::string>> normalizeSeatIds(
    const Json::Value &seats,
    std::size_t minimum)
{
    if (!seats.isArray() || seats.size() < minimum || seats.size() > 6)
    {
        return std::nullopt;
    }
    std::vector<std::string> seatIds;
    std::set<std::string> unique;
    seatIds.reserve(seats.size());
    for (const auto &seat : seats)
    {
        if (!seat.isString() || seat.asString().empty())
        {
            return std::nullopt;
        }
        auto seatId = seat.asString();
        if (!unique.insert(seatId).second)
        {
            return std::nullopt;
        }
        seatIds.push_back(std::move(seatId));
    }
    std::sort(seatIds.begin(), seatIds.end());
    return seatIds;
}

std::optional<CheckoutSessionOutcome> checkoutBusinessFailure(
    CreateReservationOutcome outcome)
{
    switch (outcome)
    {
        case CreateReservationOutcome::InvalidArgument:
            return CheckoutSessionOutcome::InvalidArgument;
        case CreateReservationOutcome::SessionNotFound:
            return CheckoutSessionOutcome::SessionNotFound;
        case CreateReservationOutcome::SessionNotAvailable:
            return CheckoutSessionOutcome::SessionNotAvailable;
        case CreateReservationOutcome::SeatConflict:
            return CheckoutSessionOutcome::SeatConflict;
        case CreateReservationOutcome::Created:
        case CreateReservationOutcome::Replayed:
        case CreateReservationOutcome::IdempotencyConflict:
        case CreateReservationOutcome::InternalError:
            return std::nullopt;
    }
    return std::nullopt;
}
}  // namespace

void CheckoutSessionService::create(std::string userId,
                                    Json::Value body,
                                    Completion completion) const
{
    if (userId.empty() || !body.isObject() ||
        !body["sessionId"].isString() ||
        body["sessionId"].asString().empty())
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto seatIds = normalizeSeatIds(body["seatIds"], 1);
    if (!seatIds)
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }

    auto state = std::make_shared<CreateState>();
    state->checkoutSessionId = "CHK-" + drogon::utils::getUuid(true);
    state->userId = std::move(userId);
    state->sessionId = body["sessionId"].asString();
    state->seatIds = std::move(*seatIds);
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failCreate(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            createValidateUser(state);
        });
}

void CheckoutSessionService::createValidateUser(
    const std::shared_ptr<CreateState> &state) const
{
    repository_.userExists(
        state->transaction,
        state->userId,
        [this, state](bool exists) {
            if (!exists)
            {
                failCreate(state, CheckoutSessionOutcome::InvalidArgument);
                return;
            }
            createValidateSession(state);
        },
        [this, state] { failCreate(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::createValidateSession(
    const std::shared_ptr<CreateState> &state) const
{
    repository_.findSessionStatus(
        state->transaction,
        state->sessionId,
        [this, state](std::optional<std::string> status) {
            if (!status)
            {
                failCreate(state, CheckoutSessionOutcome::SessionNotFound);
                return;
            }
            if (*status != "ON_SALE")
            {
                failCreate(state,
                           CheckoutSessionOutcome::SessionNotAvailable);
                return;
            }
            createValidateSeats(state);
        },
        [this, state] { failCreate(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::createValidateSeats(
    const std::shared_ptr<CreateState> &state) const
{
    repository_.findSessionSeatIds(
        state->transaction,
        state->sessionId,
        state->seatIds,
        [this, state](std::vector<std::string> found) {
            if (found != state->seatIds)
            {
                failCreate(state, CheckoutSessionOutcome::InvalidArgument);
                return;
            }
            createPrepareHolds(state);
        },
        [this, state] { failCreate(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::createPrepareHolds(
    const std::shared_ptr<CreateState> &state) const
{
    state->redisPrepareAttempted = true;
    seatHoldService_.prepare(
        state->sessionId,
        state->checkoutSessionId,
        state->seatIds,
        {},
        0,
        0,
        [this, state](SeatHoldOutcome outcome) {
            if (outcome == SeatHoldOutcome::Conflict)
            {
                failCreate(state, CheckoutSessionOutcome::TemporarySeatConflict);
                return;
            }
            createInsert(state);
        });
}

void CheckoutSessionService::createInsert(
    const std::shared_ptr<CreateState> &state) const
{
    repository_.insertCheckoutSession(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        state->sessionId,
        [this, state](CheckoutSessionRecord record) {
            state->record = std::move(record);
            state->record.value.seatIds = state->seatIds;
            createInsertSeats(state);
        },
        [this, state] { failCreate(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::createInsertSeats(
    const std::shared_ptr<CreateState> &state) const
{
    repository_.insertSeats(
        state->transaction,
        state->record.value.id,
        state->sessionId,
        state->seatIds,
        [this, state](std::size_t inserted) {
            if (inserted != state->seatIds.size())
            {
                failCreate(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            createCommit(state);
        },
        [this, state] { failCreate(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::createCommit(
    const std::shared_ptr<CreateState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failCreate(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        state->finished = true;
        auto completion = std::move(state->completion);
        completion({CheckoutSessionOutcome::Created,
                    std::move(state->record.value)});
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::replaceSeats(std::string checkoutSessionId,
                                          std::string userId,
                                          Json::Value body,
                                          Completion completion) const
{
    auto seatIds = body.isObject()
                       ? normalizeSeatIds(body["seatIds"], 0)
                       : std::nullopt;
    const auto validRevision =
        body.isObject() && body.isMember("expectedRevision") &&
        body["expectedRevision"].isInt64() &&
        body["expectedRevision"].asInt64() >= 0 &&
        body["expectedRevision"].asInt64() <
            std::numeric_limits<std::int64_t>::max();
    if (checkoutSessionId.empty() || userId.empty() || !seatIds ||
        !validRevision)
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto state = std::make_shared<ReplaceState>();
    state->checkoutSessionId = std::move(checkoutSessionId);
    state->userId = std::move(userId);
    state->seatIds = std::move(*seatIds);
    state->expectedRevision = body["expectedRevision"].asInt64();
    state->targetRevision = state->expectedRevision + 1;
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failReplace(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            replaceLock(state);
        });
}

void CheckoutSessionService::replaceLock(
    const std::shared_ptr<ReplaceState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        [this, state](std::optional<CheckoutSessionRecord> record) {
            if (!record)
            {
                failReplace(state, CheckoutSessionOutcome::NotFound);
                return;
            }
            state->record = std::move(*record);
            if (state->record.value.status != "SELECTING")
            {
                failReplace(state, CheckoutSessionOutcome::NotModifiable);
                return;
            }
            if (state->record.value.revision != state->expectedRevision)
            {
                failReplace(state, CheckoutSessionOutcome::VersionConflict);
                return;
            }
            replaceLoadCurrentSeats(state);
        },
        [this, state] { failReplace(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::replaceLoadCurrentSeats(
    const std::shared_ptr<ReplaceState> &state) const
{
    repository_.loadSeatIds(
        state->transaction,
        state->checkoutSessionId,
        [this, state](std::vector<std::string> seatIds) {
            state->oldSeatIds = std::move(seatIds);
            std::set_difference(state->seatIds.begin(),
                                state->seatIds.end(),
                                state->oldSeatIds.begin(),
                                state->oldSeatIds.end(),
                                std::back_inserter(state->addedSeatIds));
            std::set_intersection(state->seatIds.begin(),
                                  state->seatIds.end(),
                                  state->oldSeatIds.begin(),
                                  state->oldSeatIds.end(),
                                  std::back_inserter(state->retainedSeatIds));
            std::set_difference(state->oldSeatIds.begin(),
                                state->oldSeatIds.end(),
                                state->seatIds.begin(),
                                state->seatIds.end(),
                                std::back_inserter(state->removedSeatIds));
            replaceValidateSeats(state);
        },
        [this, state] {
            failReplace(state, CheckoutSessionOutcome::InternalError);
        });
}

void CheckoutSessionService::replaceValidateSeats(
    const std::shared_ptr<ReplaceState> &state) const
{
    if (state->seatIds.empty())
    {
        replacePrepareHolds(state);
        return;
    }
    repository_.findSessionSeatIds(
        state->transaction,
        state->record.value.sessionId,
        state->seatIds,
        [this, state](std::vector<std::string> found) {
            if (found != state->seatIds)
            {
                failReplace(state, CheckoutSessionOutcome::InvalidArgument);
                return;
            }
            replacePrepareHolds(state);
        },
        [this, state] { failReplace(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::replacePrepareHolds(
    const std::shared_ptr<ReplaceState> &state) const
{
    if (state->addedSeatIds.empty() && state->retainedSeatIds.empty())
    {
        replaceDeleteSeats(state);
        return;
    }
    state->redisPrepareAttempted = true;
    seatHoldService_.prepare(
        state->record.value.sessionId,
        state->checkoutSessionId,
        state->addedSeatIds,
        state->retainedSeatIds,
        state->expectedRevision,
        state->targetRevision,
        [this, state](SeatHoldOutcome outcome) {
            if (outcome == SeatHoldOutcome::Conflict)
            {
                failReplace(state, CheckoutSessionOutcome::TemporarySeatConflict);
                return;
            }
            replaceDeleteSeats(state);
        });
}

void CheckoutSessionService::replaceDeleteSeats(
    const std::shared_ptr<ReplaceState> &state) const
{
    repository_.deleteSeats(
        state->transaction,
        state->checkoutSessionId,
        [this, state] {
            if (state->seatIds.empty())
            {
                replaceTouch(state);
                return;
            }
            replaceInsertSeats(state);
        },
        [this, state] { failReplace(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::replaceInsertSeats(
    const std::shared_ptr<ReplaceState> &state) const
{
    repository_.insertSeats(
        state->transaction,
        state->checkoutSessionId,
        state->record.value.sessionId,
        state->seatIds,
        [this, state](std::size_t inserted) {
            if (inserted != state->seatIds.size())
            {
                failReplace(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            replaceTouch(state);
        },
        [this, state] { failReplace(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::replaceTouch(
    const std::shared_ptr<ReplaceState> &state) const
{
    repository_.advanceSeatRevision(
        state->transaction,
        state->checkoutSessionId,
        [this, state](std::string updatedAt, std::int64_t revision) {
            state->record.value.seatIds = state->seatIds;
            state->record.value.updatedAt = std::move(updatedAt);
            state->record.value.revision = revision;
            replaceCommit(state);
        },
        [this, state] { failReplace(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::replaceCommit(
    const std::shared_ptr<ReplaceState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failReplace(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        replaceFinish(state);
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::replaceFinish(
    const std::shared_ptr<ReplaceState> &state) const
{
    seatHoldService_.finalize(
        state->record.value.sessionId,
        state->checkoutSessionId,
        state->removedSeatIds,
        state->targetRevision,
        [state](SeatHoldOutcome) {
            state->finished = true;
            auto completion = std::move(state->completion);
            completion({CheckoutSessionOutcome::Updated,
                        std::move(state->record.value)});
        });
}

void CheckoutSessionService::get(std::string checkoutSessionId,
                                 std::string userId,
                                 Completion completion) const
{
    if (checkoutSessionId.empty() || userId.empty())
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto client = drogon::app().getDbClient("default");
    auto completionPtr =
        std::make_shared<Completion>(std::move(completion));
    repository_.findByIdForUser(
        client,
        checkoutSessionId,
        userId,
        [this, completionPtr](
            std::optional<CheckoutSessionRecord> record) {
            if (!record)
            {
                (*completionPtr)(
                    {CheckoutSessionOutcome::NotFound, std::nullopt});
                return;
            }
            resolveRecord(std::move(*record),
                          CheckoutSessionOutcome::Found,
                          std::move(*completionPtr));
        },
        [completionPtr] {
            (*completionPtr)(
                {CheckoutSessionOutcome::InternalError, std::nullopt});
        });
}

void CheckoutSessionService::listRecoverable(
    std::string userId,
    std::string sessionId,
    bool recoverable,
    ListCompletion completion) const
{
    if (userId.empty() || sessionId.empty() || !recoverable)
    {
        completion({CheckoutSessionOutcome::InvalidArgument, {}});
        return;
    }
    auto client = drogon::app().getDbClient("default");
    auto completionPtr =
        std::make_shared<ListCompletion>(std::move(completion));
    repository_.listRecoverable(
        client,
        userId,
        sessionId,
        [completionPtr](std::vector<CheckoutSessionRecord> records) {
            std::vector<CheckoutSession> values;
            values.reserve(records.size());
            for (auto &record : records)
            {
                values.push_back(std::move(record.value));
            }
            (*completionPtr)(
                {CheckoutSessionOutcome::Found, std::move(values)});
        },
        [completionPtr] {
            (*completionPtr)({CheckoutSessionOutcome::InternalError, {}});
        });
}

void CheckoutSessionService::confirm(std::string checkoutSessionId,
                                     std::string userId,
                                     Completion completion) const
{
    if (checkoutSessionId.empty() || userId.empty())
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto state = std::make_shared<ConfirmState>();
    state->checkoutSessionId = std::move(checkoutSessionId);
    state->userId = std::move(userId);
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            prepareConfirm(state);
        });
}

void CheckoutSessionService::prepareConfirm(
    const std::shared_ptr<ConfirmState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        [this, state](std::optional<CheckoutSessionRecord> record) {
            if (!record)
            {
                failConfirm(state, CheckoutSessionOutcome::NotFound);
                return;
            }
            state->record = std::move(*record);
            confirmLoadSeats(state);
        },
        [state] { failConfirm(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::confirmLoadSeats(
    const std::shared_ptr<ConfirmState> &state) const
{
    repository_.loadSeatIds(
        state->transaction,
        state->checkoutSessionId,
        [this, state](std::vector<std::string> seatIds) {
            state->record.value.seatIds = std::move(seatIds);
            const auto &status = state->record.value.status;
            if (status == "RESERVED")
            {
                state->transaction->rollback();
                state->transaction.reset();
                state->finished = true;
                auto completion = std::move(state->completion);
                const auto sessionId = state->record.value.sessionId;
                const auto checkoutSessionId = state->checkoutSessionId;
                const auto seatIds = state->record.value.seatIds;
                resolveRecord(std::move(state->record),
                              CheckoutSessionOutcome::Confirmed,
                              [this,
                               sessionId,
                               checkoutSessionId,
                               seatIds,
                               completion = std::move(completion)](
                                  CheckoutSessionResult result) mutable {
                                  seatHoldService_.release(
                                      sessionId,
                                      checkoutSessionId,
                                      seatIds,
                                      [completion = std::move(completion),
                                       result = std::move(result)](
                                          SeatHoldOutcome) mutable {
                                          completion(std::move(result));
                                      });
                              });
                return;
            }
            if (status == "ABANDONED")
            {
                failConfirm(state,
                            CheckoutSessionOutcome::NotConfirmable);
                return;
            }
            if (state->record.value.seatIds.empty() ||
                state->record.value.seatIds.size() > 6)
            {
                failConfirm(state,
                            status == "SELECTING"
                                ? CheckoutSessionOutcome::InvalidArgument
                                : CheckoutSessionOutcome::InternalError);
                return;
            }
            if (status == "SUBMITTING")
            {
                if (!state->record.activeConfirmIdempotencyKey)
                {
                    failConfirm(state, CheckoutSessionOutcome::InternalError);
                    return;
                }
                state->idempotencyKey =
                    *state->record.activeConfirmIdempotencyKey;
                confirmPrepareCommit(state);
                return;
            }
            if (status != "SELECTING")
            {
                failConfirm(state,
                            CheckoutSessionOutcome::NotConfirmable);
                return;
            }
            state->idempotencyKey =
                "CHK-CONFIRM-" + drogon::utils::getUuid(true);
            confirmEnsureHolds(state);
        },
        [state] { failConfirm(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::confirmEnsureHolds(
    const std::shared_ptr<ConfirmState> &state) const
{
    seatHoldService_.ensure(
        state->record.value.sessionId,
        state->checkoutSessionId,
        state->record.value.seatIds,
        state->record.value.revision,
        [this, state](SeatHoldOutcome outcome) {
            if (outcome == SeatHoldOutcome::Conflict)
            {
                failConfirm(state, CheckoutSessionOutcome::TemporarySeatConflict);
                return;
            }
            freezeConfirm(state);
        });
}

void CheckoutSessionService::freezeConfirm(
    const std::shared_ptr<ConfirmState> &state) const
{
    repository_.setSubmitting(
        state->transaction,
        state->checkoutSessionId,
        state->idempotencyKey,
        [this, state](std::string updatedAt) {
            state->record.value.status = "SUBMITTING";
            state->record.value.updatedAt = std::move(updatedAt);
            state->record.activeConfirmIdempotencyKey =
                state->idempotencyKey;
            confirmPrepareCommit(state);
        },
        [state] { failConfirm(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::confirmPrepareCommit(
    const std::shared_ptr<ConfirmState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failConfirm(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        runFormalReservation(state);
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::runFormalReservation(
    const std::shared_ptr<ConfirmState> &state) const
{
    reservationService_.createReservationForCheckout(
        state->userId,
        state->idempotencyKey,
        state->record.value.sessionId,
        state->record.value.seatIds,
        [this, state](CreateReservationResult result) {
            if ((result.outcome == CreateReservationOutcome::Created ||
                 result.outcome == CreateReservationOutcome::Replayed) &&
                result.value)
            {
                state->formalResult = std::move(*result.value);
                finalizeReserved(state);
                return;
            }
            if (auto outcome = checkoutBusinessFailure(result.outcome))
            {
                state->businessFailure = *outcome;
                resetAfterBusinessFailure(state);
                return;
            }
            failConfirm(state, CheckoutSessionOutcome::InternalError);
        });
}

void CheckoutSessionService::finalizeReserved(
    const std::shared_ptr<ConfirmState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            finalizeReservedLocked(state);
        });
}

void CheckoutSessionService::finalizeReservedLocked(
    const std::shared_ptr<ConfirmState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        [this, state](std::optional<CheckoutSessionRecord> current) {
            if (!current)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            const auto reservationId = state->formalResult.reservation.id;
            if (current->value.status == "RESERVED" &&
                current->value.reservationId &&
                *current->value.reservationId == reservationId)
            {
                state->record.value.status = "RESERVED";
                state->record.value.reservationId = reservationId;
                state->record.value.updatedAt = current->value.updatedAt;
                state->record.value.formalResult = state->formalResult;
                state->transaction->rollback();
                state->transaction.reset();
                seatHoldService_.release(
                    state->record.value.sessionId,
                    state->checkoutSessionId,
                    state->record.value.seatIds,
                    [state](SeatHoldOutcome) {
                        state->finished = true;
                        auto completion = std::move(state->completion);
                        completion({CheckoutSessionOutcome::Confirmed,
                                    std::move(state->record.value)});
                    });
                return;
            }
            if (current->value.status != "SUBMITTING" ||
                !current->activeConfirmIdempotencyKey ||
                *current->activeConfirmIdempotencyKey !=
                    state->idempotencyKey)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            repository_.setReserved(
                state->transaction,
                state->checkoutSessionId,
                state->idempotencyKey,
                reservationId,
                [this, state, reservationId](
                    std::optional<std::string> updatedAt) {
                    if (!updatedAt)
                    {
                        failConfirm(
                            state, CheckoutSessionOutcome::InternalError);
                        return;
                    }
                    state->record.value.status = "RESERVED";
                    state->record.value.reservationId = reservationId;
                    state->record.value.updatedAt = std::move(*updatedAt);
                    state->record.value.formalResult = state->formalResult;
                    finalizeReservedCommit(state);
                },
                [state] {
                    failConfirm(state,
                                CheckoutSessionOutcome::InternalError);
                });
        },
        [state] { failConfirm(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::finalizeReservedCommit(
    const std::shared_ptr<ConfirmState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failConfirm(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        seatHoldService_.release(
            state->record.value.sessionId,
            state->checkoutSessionId,
            state->record.value.seatIds,
            [state](SeatHoldOutcome) {
                state->finished = true;
                auto completion = std::move(state->completion);
                completion({CheckoutSessionOutcome::Confirmed,
                            std::move(state->record.value)});
            });
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::resetAfterBusinessFailure(
    const std::shared_ptr<ConfirmState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            resetAfterBusinessFailureLocked(state);
        });
}

void CheckoutSessionService::resetAfterBusinessFailureLocked(
    const std::shared_ptr<ConfirmState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        [this, state](std::optional<CheckoutSessionRecord> current) {
            if (!current)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            if (current->value.status == "SELECTING" &&
                !current->activeConfirmIdempotencyKey)
            {
                state->transaction->rollback();
                state->transaction.reset();
                state->finished = true;
                auto completion = std::move(state->completion);
                completion({state->businessFailure, std::nullopt});
                return;
            }
            if (current->value.status != "SUBMITTING" ||
                !current->activeConfirmIdempotencyKey ||
                *current->activeConfirmIdempotencyKey !=
                    state->idempotencyKey)
            {
                failConfirm(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            resetAfterBusinessFailureRelease(state);
        },
        [state] { failConfirm(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::resetAfterBusinessFailureRelease(
    const std::shared_ptr<ConfirmState> &state) const
{
    seatHoldService_.release(
        state->record.value.sessionId,
        state->checkoutSessionId,
        state->record.value.seatIds,
        [this, state](SeatHoldOutcome) {
            repository_.resetSelecting(
                state->transaction,
                state->checkoutSessionId,
                state->idempotencyKey,
                [this, state](std::optional<std::string> updatedAt) {
                    if (!updatedAt)
                    {
                        failConfirm(
                            state, CheckoutSessionOutcome::InternalError);
                        return;
                    }
                    state->record.value.status = "SELECTING";
                    state->record.value.updatedAt = std::move(*updatedAt);
                    state->record.activeConfirmIdempotencyKey.reset();
                    resetAfterBusinessFailureCommit(state);
                },
                [state] {
                    failConfirm(state,
                                CheckoutSessionOutcome::InternalError);
                });
        });
}

void CheckoutSessionService::resetAfterBusinessFailureCommit(
    const std::shared_ptr<ConfirmState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([state](bool committed) {
        if (!committed)
        {
            failConfirm(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        state->finished = true;
        auto completion = std::move(state->completion);
        completion({state->businessFailure, std::nullopt});
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::resolveRecord(
    CheckoutSessionRecord record,
    CheckoutSessionOutcome successOutcome,
    Completion completion) const
{
    if (record.value.status != "SUBMITTING" &&
        record.value.status != "RESERVED")
    {
        completion({successOutcome, std::move(record.value)});
        return;
    }
    if (!record.activeConfirmIdempotencyKey)
    {
        completion({CheckoutSessionOutcome::InternalError, std::nullopt});
        return;
    }
    auto state = std::make_shared<ResolveState>();
    state->record = std::move(record);
    state->successOutcome = successOutcome;
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    reservationRepository_.findCompleteByIdempotency(
        client,
        state->record.value.userId,
        *state->record.activeConfirmIdempotencyKey,
        [this, state](std::optional<ReservationResult> result) {
            resolveFoundFormalResult(state, std::move(result));
        },
        [state] { failResolve(state); });
}

void CheckoutSessionService::resolveFoundFormalResult(
    const std::shared_ptr<ResolveState> &state,
    std::optional<ReservationResult> result) const
{
    if (!result)
    {
        if (state->record.value.status == "SUBMITTING")
        {
            state->finished = true;
            auto completion = std::move(state->completion);
            completion({state->successOutcome,
                        std::move(state->record.value)});
            return;
        }
        failResolve(state);
        return;
    }
    state->formalResult = std::move(*result);
    if (state->record.value.status == "RESERVED")
    {
        if (!state->record.value.reservationId ||
            *state->record.value.reservationId !=
                state->formalResult.reservation.id)
        {
            failResolve(state);
            return;
        }
        state->record.value.formalResult = state->formalResult;
        finishResolved(state);
        return;
    }
    reconcileRecord(state);
}

void CheckoutSessionService::reconcileRecord(
    const std::shared_ptr<ResolveState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failResolve(state);
                return;
            }
            state->transaction = tx;
            reconcileRecordLocked(state);
        });
}

void CheckoutSessionService::reconcileRecordLocked(
    const std::shared_ptr<ResolveState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->record.value.id,
        state->record.value.userId,
        [this, state](std::optional<CheckoutSessionRecord> current) {
            if (!current)
            {
                failResolve(state);
                return;
            }
            const auto reservationId = state->formalResult.reservation.id;
            if (current->value.status == "RESERVED" &&
                current->value.reservationId &&
                *current->value.reservationId == reservationId)
            {
                state->record.value.status = "RESERVED";
                state->record.value.reservationId = reservationId;
                state->record.value.updatedAt = current->value.updatedAt;
                state->record.value.formalResult = state->formalResult;
                state->transaction->rollback();
                state->transaction.reset();
                finishResolved(state);
                return;
            }
            if (current->value.status != "SUBMITTING" ||
                !current->activeConfirmIdempotencyKey ||
                *current->activeConfirmIdempotencyKey !=
                    *state->record.activeConfirmIdempotencyKey)
            {
                failResolve(state);
                return;
            }
            repository_.setReserved(
                state->transaction,
                state->record.value.id,
                *state->record.activeConfirmIdempotencyKey,
                reservationId,
                [this, state, reservationId](
                    std::optional<std::string> updatedAt) {
                    if (!updatedAt)
                    {
                        failResolve(state);
                        return;
                    }
                    state->record.value.status = "RESERVED";
                    state->record.value.reservationId = reservationId;
                    state->record.value.updatedAt = std::move(*updatedAt);
                    state->record.value.formalResult = state->formalResult;
                    reconcileRecordCommit(state);
                },
                [state] { failResolve(state); });
        },
        [state] { failResolve(state); });
}

void CheckoutSessionService::reconcileRecordCommit(
    const std::shared_ptr<ResolveState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failResolve(state);
            return;
        }
        finishResolved(state);
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::finishResolved(
    const std::shared_ptr<ResolveState> &state) const
{
    seatHoldService_.release(
        state->record.value.sessionId,
        state->record.value.id,
        state->record.value.seatIds,
        [state](SeatHoldOutcome) {
            state->finished = true;
            auto completion = std::move(state->completion);
            completion({state->successOutcome, std::move(state->record.value)});
        });
}

void CheckoutSessionService::abandon(std::string checkoutSessionId,
                                     std::string userId,
                                     Completion completion) const
{
    if (checkoutSessionId.empty() || userId.empty())
    {
        completion({CheckoutSessionOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto state = std::make_shared<AbandonState>();
    state->checkoutSessionId = std::move(checkoutSessionId);
    state->userId = std::move(userId);
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const CheckoutSessionRepository::TransactionPtr &tx) {
            if (!tx)
            {
                failAbandon(state, CheckoutSessionOutcome::InternalError);
                return;
            }
            state->transaction = tx;
            abandonLock(state);
        });
}

void CheckoutSessionService::abandonLock(
    const std::shared_ptr<AbandonState> &state) const
{
    repository_.lockByIdForUser(
        state->transaction,
        state->checkoutSessionId,
        state->userId,
        [this, state](std::optional<CheckoutSessionRecord> record) {
            if (!record)
            {
                failAbandon(state, CheckoutSessionOutcome::NotFound);
                return;
            }
            state->record = std::move(*record);
            if (state->record.value.status == "ABANDONED")
            {
                state->transaction->rollback();
                state->transaction.reset();
                state->finished = true;
                auto completion = std::move(state->completion);
                completion({CheckoutSessionOutcome::Abandoned,
                            std::move(state->record.value)});
                return;
            }
            if (state->record.value.status != "SELECTING")
            {
                failAbandon(state,
                            CheckoutSessionOutcome::NotAbandonable);
                return;
            }
            abandonLoadSeats(state);
        },
        [state] { failAbandon(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::abandonLoadSeats(
    const std::shared_ptr<AbandonState> &state) const
{
    repository_.loadSeatIds(
        state->transaction,
        state->checkoutSessionId,
        [this, state](std::vector<std::string> seatIds) {
            state->record.value.seatIds = std::move(seatIds);
            repository_.setAbandoned(
                state->transaction,
                state->checkoutSessionId,
                [this, state](std::optional<std::string> updatedAt) {
                    if (!updatedAt)
                    {
                        failAbandon(
                            state, CheckoutSessionOutcome::InternalError);
                        return;
                    }
                    state->record.value.status = "ABANDONED";
                    state->record.value.updatedAt = std::move(*updatedAt);
                    abandonCommit(state);
                },
                [state] {
                    failAbandon(state,
                                CheckoutSessionOutcome::InternalError);
                });
        },
        [state] { failAbandon(state, CheckoutSessionOutcome::InternalError); });
}

void CheckoutSessionService::abandonCommit(
    const std::shared_ptr<AbandonState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            failAbandon(state, CheckoutSessionOutcome::InternalError);
            return;
        }
        seatHoldService_.release(
            state->record.value.sessionId,
            state->checkoutSessionId,
            state->record.value.seatIds,
            [state](SeatHoldOutcome) {
                state->finished = true;
                auto completion = std::move(state->completion);
                completion({CheckoutSessionOutcome::Abandoned,
                            std::move(state->record.value)});
            });
    });
    state->transaction.reset();
    transaction.reset();
}

void CheckoutSessionService::reconcileSubmitting(
    std::size_t batchSize,
    ReconciliationCompletion completion) const
{
    if (batchSize == 0)
    {
        completion(0, false);
        return;
    }
    auto client = drogon::app().getDbClient("default");
    auto completionPtr = std::make_shared<ReconciliationCompletion>(
        std::move(completion));
    repository_.reconcileSubmitting(
        client,
        batchSize,
        [completionPtr](std::size_t repaired) {
            (*completionPtr)(repaired, true);
        },
        [completionPtr] { (*completionPtr)(0, false); });
}

void CheckoutSessionService::failCreate(
    const std::shared_ptr<CreateState> &state,
    CheckoutSessionOutcome outcome) const
{
    if (state->finished)
    {
        return;
    }
    state->finished = true;
    auto finish = [state, outcome](SeatHoldOutcome) {
        if (state->transaction)
        {
            state->transaction->rollback();
            state->transaction.reset();
        }
        auto completion = std::move(state->completion);
        completion({outcome, std::nullopt});
    };
    if (state->redisPrepareAttempted)
    {
        seatHoldService_.abort(state->sessionId,
                               state->checkoutSessionId,
                               state->seatIds,
                               0,
                               std::move(finish));
        return;
    }
    finish(SeatHoldOutcome::Applied);
}

void CheckoutSessionService::failReplace(
    const std::shared_ptr<ReplaceState> &state,
    CheckoutSessionOutcome outcome) const
{
    if (state->finished)
    {
        return;
    }
    state->finished = true;
    auto finish = [state, outcome](SeatHoldOutcome) {
        if (state->transaction)
        {
            state->transaction->rollback();
            state->transaction.reset();
        }
        auto completion = std::move(state->completion);
        completion({outcome, std::nullopt});
    };
    if (state->redisPrepareAttempted)
    {
        seatHoldService_.abort(state->record.value.sessionId,
                               state->checkoutSessionId,
                               state->addedSeatIds,
                               state->targetRevision,
                               std::move(finish));
        return;
    }
    finish(SeatHoldOutcome::Applied);
}

void CheckoutSessionService::failConfirm(
    const std::shared_ptr<ConfirmState> &state,
    CheckoutSessionOutcome outcome)
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
    state->finished = true;
    auto completion = std::move(state->completion);
    completion({outcome, std::nullopt});
}

void CheckoutSessionService::failResolve(
    const std::shared_ptr<ResolveState> &state)
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
    state->finished = true;
    auto completion = std::move(state->completion);
    completion({CheckoutSessionOutcome::InternalError, std::nullopt});
}

void CheckoutSessionService::failAbandon(
    const std::shared_ptr<AbandonState> &state,
    CheckoutSessionOutcome outcome)
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
    state->finished = true;
    auto completion = std::move(state->completion);
    completion({outcome, std::nullopt});
}
}  // namespace ticketing
