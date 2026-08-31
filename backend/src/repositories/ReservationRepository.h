#pragma once

#include "dto/TicketDtos.h"

#include <drogon/orm/DbClient.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
struct ReservationSessionRow
{
    std::string eventId;
    std::string status;
};

struct LockedSessionSeatRow
{
    std::string id;
    std::string sessionId;
    std::string status;
    std::int64_t price{};
};

class ReservationRepository
{
  public:
    using TransactionPtr = std::shared_ptr<drogon::orm::Transaction>;
    using ErrorCallback = std::function<void()>;

    void findCompleteByIdempotency(
        const drogon::orm::DbClientPtr &client,
        const std::string &userId,
        const std::string &idempotencyKey,
        std::function<void(std::optional<ReservationResult>)> onSuccess,
        ErrorCallback onError) const;

    void userExists(const TransactionPtr &transaction,
                    const std::string &userId,
                    std::function<void(bool)> onSuccess,
                    ErrorCallback onError) const;

    void findSession(const TransactionPtr &transaction,
                     const std::string &sessionId,
                     std::function<void(std::optional<ReservationSessionRow>)>
                         onSuccess,
                     ErrorCallback onError) const;

    void insertReservation(
        const TransactionPtr &transaction,
        const std::string &reservationId,
        const std::string &userId,
        const std::string &sessionId,
        const std::string &idempotencyKey,
        std::function<void(std::optional<Reservation>)> onSuccess,
        ErrorCallback onError) const;

    void lockSessionSeats(
        const TransactionPtr &transaction,
        const std::vector<std::string> &seatIds,
        std::function<void(std::vector<LockedSessionSeatRow>)> onSuccess,
        ErrorCallback onError) const;

    void holdSessionSeats(const TransactionPtr &transaction,
                          const std::string &reservationId,
                          const std::string &sessionId,
                          const std::vector<std::string> &seatIds,
                          std::function<void(std::size_t)> onSuccess,
                          ErrorCallback onError) const;

    void insertReservationSeats(
        const TransactionPtr &transaction,
        const std::string &reservationId,
        const std::string &sessionId,
        const std::vector<LockedSessionSeatRow> &seats,
        std::function<void(std::size_t)> onSuccess,
        ErrorCallback onError) const;

    void insertOrder(const TransactionPtr &transaction,
                     const std::string &orderId,
                     const std::string &reservationId,
                     std::int64_t totalAmount,
                     std::function<void(TicketOrder)> onSuccess,
                     ErrorCallback onError) const;
};
}  // namespace ticketing
