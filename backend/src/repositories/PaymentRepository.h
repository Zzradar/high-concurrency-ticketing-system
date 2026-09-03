#pragma once

#include "dto/TicketDtos.h"

#include <drogon/orm/DbClient.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

namespace ticketing
{
struct LockedPaymentAttempt
{
    PaymentAttempt value;
    bool deadlinePassed{};
    bool startedBeforeOrderExpiry{};
};

class PaymentRepository
{
  public:
    using TransactionPtr = std::shared_ptr<drogon::orm::Transaction>;
    using ErrorCallback = std::function<void()>;

    void findByIdForUser(const drogon::orm::DbClientPtr &client,
                         const std::string &attemptId,
                         const std::string &userId,
                         std::function<void(std::optional<PaymentAttempt>)> onSuccess,
                         ErrorCallback onError) const;
    void findLastAcceptedForOrder(
        const drogon::orm::DbClientPtr &client,
        const std::string &orderId,
        std::function<void(std::optional<PaymentAttempt>)> onSuccess,
        ErrorCallback onError) const;
    void lockProcessingForOrder(
        const TransactionPtr &transaction,
        const std::string &orderId,
        std::function<void(std::optional<LockedPaymentAttempt>)> onSuccess,
        ErrorCallback onError) const;
    void lockByIdForOrder(
        const TransactionPtr &transaction,
        const std::string &attemptId,
        const std::string &orderId,
        std::function<void(std::optional<LockedPaymentAttempt>)> onSuccess,
        ErrorCallback onError) const;
    void createAttempt(const TransactionPtr &transaction,
                       const std::string &attemptId,
                       const std::string &orderId,
                       double delaySeconds,
                       double graceSeconds,
                       std::function<void(PaymentAttempt)> onSuccess,
                       ErrorCallback onError) const;
    void markTimedOut(const TransactionPtr &transaction,
                      const std::string &attemptId,
                      std::function<void(std::size_t)> onSuccess,
                      ErrorCallback onError) const;
    void markFailed(const TransactionPtr &transaction,
                    const std::string &attemptId,
                    const std::string &reason,
                    std::function<void(std::size_t)> onSuccess,
                    ErrorCallback onError) const;
    void markSucceeded(const TransactionPtr &transaction,
                       const std::string &attemptId,
                       bool accepted,
                       std::function<void(std::size_t)> onSuccess,
                       ErrorCallback onError) const;
    void insertRefund(const TransactionPtr &transaction,
                      const std::string &refundId,
                      const std::string &attemptId,
                      const std::string &orderId,
                      std::int64_t amount,
                      const std::string &reason,
                      std::function<void(std::size_t)> onSuccess,
                      ErrorCallback onError) const;
};
}  // namespace ticketing
