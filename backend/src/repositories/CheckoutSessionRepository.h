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
struct CheckoutSessionRecord
{
    CheckoutSession value;
    std::optional<std::string> activeConfirmIdempotencyKey;
};

class CheckoutSessionRepository
{
  public:
    using TransactionPtr = std::shared_ptr<drogon::orm::Transaction>;
    using ErrorCallback = std::function<void()>;

    void userExists(const TransactionPtr &transaction,
                    const std::string &userId,
                    std::function<void(bool)> onSuccess,
                    ErrorCallback onError) const;
    void findSessionStatus(
        const TransactionPtr &transaction,
        const std::string &sessionId,
        std::function<void(std::optional<std::string>)> onSuccess,
        ErrorCallback onError) const;
    void findSessionSeatIds(
        const TransactionPtr &transaction,
        const std::string &sessionId,
        const std::vector<std::string> &seatIds,
        std::function<void(std::vector<std::string>)> onSuccess,
        ErrorCallback onError) const;
    void insertCheckoutSession(
        const TransactionPtr &transaction,
        const std::string &checkoutSessionId,
        const std::string &userId,
        const std::string &sessionId,
        std::function<void(CheckoutSessionRecord)> onSuccess,
        ErrorCallback onError) const;
    void insertSeats(const TransactionPtr &transaction,
                     const std::string &checkoutSessionId,
                     const std::string &sessionId,
                     const std::vector<std::string> &seatIds,
                     std::function<void(std::size_t)> onSuccess,
                     ErrorCallback onError) const;
    void lockByIdForUser(
        const TransactionPtr &transaction,
        const std::string &checkoutSessionId,
        const std::string &userId,
        std::function<void(std::optional<CheckoutSessionRecord>)> onSuccess,
        ErrorCallback onError) const;
    void loadSeatIds(const TransactionPtr &transaction,
                     const std::string &checkoutSessionId,
                     std::function<void(std::vector<std::string>)> onSuccess,
                     ErrorCallback onError) const;
    void deleteSeats(const TransactionPtr &transaction,
                     const std::string &checkoutSessionId,
                     std::function<void()> onSuccess,
                     ErrorCallback onError) const;
    void touch(const TransactionPtr &transaction,
               const std::string &checkoutSessionId,
               std::function<void(std::string)> onSuccess,
               ErrorCallback onError) const;
    void setSubmitting(const TransactionPtr &transaction,
                       const std::string &checkoutSessionId,
                       const std::string &idempotencyKey,
                       std::function<void(std::string)> onSuccess,
                       ErrorCallback onError) const;
    void setReserved(const TransactionPtr &transaction,
                     const std::string &checkoutSessionId,
                     const std::string &idempotencyKey,
                     const std::string &reservationId,
                     std::function<void(std::optional<std::string>)> onSuccess,
                     ErrorCallback onError) const;
    void resetSelecting(const TransactionPtr &transaction,
                        const std::string &checkoutSessionId,
                        const std::string &idempotencyKey,
                        std::function<void(std::optional<std::string>)> onSuccess,
                        ErrorCallback onError) const;
    void setAbandoned(const TransactionPtr &transaction,
                      const std::string &checkoutSessionId,
                      std::function<void(std::optional<std::string>)> onSuccess,
                      ErrorCallback onError) const;

    void findByIdForUser(
        const drogon::orm::DbClientPtr &client,
        const std::string &checkoutSessionId,
        const std::string &userId,
        std::function<void(std::optional<CheckoutSessionRecord>)> onSuccess,
        ErrorCallback onError) const;
    void listRecoverable(
        const drogon::orm::DbClientPtr &client,
        const std::string &userId,
        const std::string &sessionId,
        std::function<void(std::vector<CheckoutSessionRecord>)> onSuccess,
        ErrorCallback onError) const;
    void reconcileSubmitting(
        const drogon::orm::DbClientPtr &client,
        std::size_t batchSize,
        std::function<void(std::size_t)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
