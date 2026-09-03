#pragma once

#include "dto/TicketDtos.h"
#include "repositories/CheckoutSessionRepository.h"
#include "services/ReservationService.h"
#include "services/SeatHoldService.h"

#include <json/json.h>

#include <cstddef>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
enum class CheckoutSessionOutcome
{
    Created,
    Found,
    Updated,
    Confirmed,
    Abandoned,
    InvalidArgument,
    SessionNotFound,
    SessionNotAvailable,
    NotFound,
    NotModifiable,
    VersionConflict,
    NotConfirmable,
    NotAbandonable,
    SeatConflict,
    TemporarySeatConflict,
    InternalError,
};

struct CheckoutSessionResult
{
    CheckoutSessionOutcome outcome{CheckoutSessionOutcome::InternalError};
    std::optional<CheckoutSession> value;
    std::string disposition;
};

struct CheckoutSessionListResult
{
    CheckoutSessionOutcome outcome{CheckoutSessionOutcome::InternalError};
    std::vector<CheckoutSession> values;
};

class CheckoutSessionService
{
  public:
    using Completion = std::function<void(CheckoutSessionResult)>;
    using ListCompletion = std::function<void(CheckoutSessionListResult)>;
    using ReconciliationCompletion =
        std::function<void(std::size_t repaired, bool succeeded)>;

    void create(std::string userId,
                Json::Value body,
                Completion completion) const;
    void get(std::string checkoutSessionId,
             std::string userId,
             Completion completion) const;
    void listRecoverable(std::string userId,
                         std::string sessionId,
                         bool recoverable,
                         ListCompletion completion) const;
    void replaceSeats(std::string checkoutSessionId,
                      std::string userId,
                      Json::Value body,
                      Completion completion) const;
    void confirm(std::string checkoutSessionId,
                 std::string userId,
                 Completion completion) const;
    void abandon(std::string checkoutSessionId,
                 std::string userId,
                 Completion completion) const;
    void reconcileSubmitting(std::size_t batchSize,
                             ReconciliationCompletion completion) const;

  private:
    struct CreateState;
    struct ReplaceState;
    struct ConfirmState;
    struct ResolveState;
    struct AbandonState;

    void createValidateUser(const std::shared_ptr<CreateState> &state) const;
    void createValidateSession(const std::shared_ptr<CreateState> &state) const;
    void createValidateSeats(const std::shared_ptr<CreateState> &state) const;
    void createPrepareHolds(const std::shared_ptr<CreateState> &state) const;
    void createInsert(const std::shared_ptr<CreateState> &state) const;
    void createInsertSeats(const std::shared_ptr<CreateState> &state) const;
    void createCommit(const std::shared_ptr<CreateState> &state) const;

    void replaceLock(const std::shared_ptr<ReplaceState> &state) const;
    void replaceLoadCurrentSeats(const std::shared_ptr<ReplaceState> &state) const;
    void replaceValidateSeats(const std::shared_ptr<ReplaceState> &state) const;
    void replacePrepareHolds(const std::shared_ptr<ReplaceState> &state) const;
    void replaceDeleteSeats(const std::shared_ptr<ReplaceState> &state) const;
    void replaceInsertSeats(const std::shared_ptr<ReplaceState> &state) const;
    void replaceTouch(const std::shared_ptr<ReplaceState> &state) const;
    void replaceCommit(const std::shared_ptr<ReplaceState> &state) const;
    void replaceFinish(const std::shared_ptr<ReplaceState> &state) const;

    void prepareConfirm(const std::shared_ptr<ConfirmState> &state) const;
    void confirmLoadSeats(const std::shared_ptr<ConfirmState> &state) const;
    void confirmEnsureHolds(const std::shared_ptr<ConfirmState> &state) const;
    void freezeConfirm(const std::shared_ptr<ConfirmState> &state) const;
    void confirmPrepareCommit(const std::shared_ptr<ConfirmState> &state) const;
    void runFormalReservation(const std::shared_ptr<ConfirmState> &state) const;
    void finalizeReserved(const std::shared_ptr<ConfirmState> &state) const;
    void finalizeReservedLocked(const std::shared_ptr<ConfirmState> &state) const;
    void finalizeReservedCommit(const std::shared_ptr<ConfirmState> &state) const;
    void resetAfterBusinessFailure(
        const std::shared_ptr<ConfirmState> &state) const;
    void resetAfterBusinessFailureLocked(
        const std::shared_ptr<ConfirmState> &state) const;
    void resetAfterBusinessFailureRelease(
        const std::shared_ptr<ConfirmState> &state) const;
    void resetAfterBusinessFailureCommit(
        const std::shared_ptr<ConfirmState> &state) const;

    void resolveRecord(CheckoutSessionRecord record,
                       CheckoutSessionOutcome successOutcome,
                       Completion completion) const;
    void resolveFoundFormalResult(
        const std::shared_ptr<ResolveState> &state,
        std::optional<ReservationResult> result) const;
    void reconcileRecord(const std::shared_ptr<ResolveState> &state) const;
    void reconcileRecordLocked(const std::shared_ptr<ResolveState> &state) const;
    void reconcileRecordCommit(const std::shared_ptr<ResolveState> &state) const;
    void finishResolved(const std::shared_ptr<ResolveState> &state) const;

    void abandonLock(const std::shared_ptr<AbandonState> &state) const;
    void abandonLoadSeats(const std::shared_ptr<AbandonState> &state) const;
    void abandonCommit(const std::shared_ptr<AbandonState> &state) const;

    void failCreate(const std::shared_ptr<CreateState> &state,
                    CheckoutSessionOutcome outcome) const;
    void failReplace(const std::shared_ptr<ReplaceState> &state,
                     CheckoutSessionOutcome outcome) const;
    static void failConfirm(const std::shared_ptr<ConfirmState> &state,
                            CheckoutSessionOutcome outcome);
    static void failResolve(const std::shared_ptr<ResolveState> &state);
    static void failAbandon(const std::shared_ptr<AbandonState> &state,
                            CheckoutSessionOutcome outcome);

    CheckoutSessionRepository repository_;
    ReservationRepository reservationRepository_;
    ReservationService reservationService_;
    SeatHoldService seatHoldService_;
};
}  // namespace ticketing
