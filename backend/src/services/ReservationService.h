#pragma once

#include "dto/TicketDtos.h"
#include "repositories/ReservationRepository.h"
#include "repositories/NotificationRepository.h"

#include <json/json.h>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
struct CreateReservationInput
{
    std::string userId;
    std::string idempotencyKey;
    Json::Value body;
};

enum class CreateReservationOutcome
{
    Created,
    Replayed,
    InvalidArgument,
    SessionNotFound,
    SessionNotAvailable,
    SeatConflict,
    IdempotencyConflict,
    InternalError,
};

struct CreateReservationResult
{
    CreateReservationOutcome outcome{CreateReservationOutcome::InternalError};
    std::optional<ReservationResult> value;
};

class ReservationService
{
  public:
    using Completion = std::function<void(CreateReservationResult)>;

    void createReservation(CreateReservationInput input,
                           Completion completion) const;

    void createReservationForCheckout(
        std::string userId,
        std::string idempotencyKey,
        std::string sessionId,
        std::vector<std::string> seatIds,
        Completion completion) const;

  private:
    struct FlowState;

    void queryExisting(const std::shared_ptr<FlowState> &state,
                       bool required) const;
    void startTransaction(const std::shared_ptr<FlowState> &state) const;
    void validateUser(const std::shared_ptr<FlowState> &state) const;
    void validateSession(const std::shared_ptr<FlowState> &state) const;
    void arbitrateIdempotency(
        const std::shared_ptr<FlowState> &state) const;
    void lockSeats(const std::shared_ptr<FlowState> &state) const;
    void holdSeats(const std::shared_ptr<FlowState> &state) const;
    void insertSeatSnapshots(
        const std::shared_ptr<FlowState> &state) const;
    void createOrder(const std::shared_ptr<FlowState> &state) const;
    void createOrderNotification(const std::shared_ptr<FlowState> &state) const;
    void commit(const std::shared_ptr<FlowState> &state) const;
    static void fail(const std::shared_ptr<FlowState> &state,
                     CreateReservationOutcome outcome);
    static void finish(const std::shared_ptr<FlowState> &state,
                       CreateReservationResult result);

    ReservationRepository repository_;
    NotificationRepository notificationRepository_;
};
}  // namespace ticketing
