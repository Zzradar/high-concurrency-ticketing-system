#pragma once

#include "dto/TicketDtos.h"

#include <drogon/orm/DbClient.h>

#include <cstddef>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
struct ExpirableOrderRow
{
    std::string id;
    std::string reservationId;
    std::string status;
    bool expired{};
};

struct ExpiryReservationRow
{
    std::string id;
    std::string status;
};

struct ExpirySessionSeatRow
{
    std::string id;
    std::string status;
    std::optional<std::string> currentReservationId;
};

class OrderRepository
{
  public:
    using TransactionPtr = std::shared_ptr<drogon::orm::Transaction>;
    using ErrorCallback = std::function<void()>;

    void userExists(const drogon::orm::DbClientPtr &client,
                    const std::string &userId,
                    std::function<void(bool)> onSuccess,
                    ErrorCallback onError) const;

    void findByIdForUser(
        const drogon::orm::DbClientPtr &client,
        const std::string &orderId,
        const std::string &userId,
        std::function<void(std::optional<TicketOrder>)> onSuccess,
        ErrorCallback onError) const;

    void findExpiredCandidateIds(
        const drogon::orm::DbClientPtr &client,
        std::size_t batchSize,
        std::function<void(std::vector<std::string>)> onSuccess,
        ErrorCallback onError) const;

    void lockOrderForExpiry(
        const TransactionPtr &transaction,
        const std::string &orderId,
        std::function<void(std::optional<ExpirableOrderRow>)> onSuccess,
        ErrorCallback onError) const;

    void lockReservationForExpiry(
        const TransactionPtr &transaction,
        const std::string &reservationId,
        std::function<void(std::optional<ExpiryReservationRow>)> onSuccess,
        ErrorCallback onError) const;

    void lockReservationSeatsForExpiry(
        const TransactionPtr &transaction,
        const std::string &reservationId,
        std::function<void(std::vector<ExpirySessionSeatRow>)> onSuccess,
        ErrorCallback onError) const;

    void releaseReservationSeats(const TransactionPtr &transaction,
                                 const std::string &reservationId,
                                 std::function<void(std::size_t)> onSuccess,
                                 ErrorCallback onError) const;

    void expireReservation(const TransactionPtr &transaction,
                           const std::string &reservationId,
                           std::function<void(std::size_t)> onSuccess,
                           ErrorCallback onError) const;

    void expireOrder(const TransactionPtr &transaction,
                     const std::string &orderId,
                     std::function<void(std::size_t)> onSuccess,
                     ErrorCallback onError) const;
};
}  // namespace ticketing
