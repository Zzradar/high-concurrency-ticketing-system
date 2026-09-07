#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

namespace ticketing
{
enum class ProviderTransportOutcome { Success, RetryableError, PermanentError };
enum class ProviderPaymentState { Processing, ActionRequired, Succeeded, Failed };
enum class ProviderRefundState { Processing, ActionRequired, Succeeded, Failed };

struct ProviderPayment
{
    std::string provider;
    std::string providerPaymentId;
    std::string providerStatus;
    ProviderPaymentState mappedState{ProviderPaymentState::Processing};
    std::optional<std::string> clientSecret;
    std::optional<std::string> failureCode;
    std::optional<std::string> failureMessage;
    bool terminal{};
};

struct ProviderRefund
{
    std::string provider;
    std::string providerRefundId;
    std::string providerStatus;
    ProviderRefundState mappedState{ProviderRefundState::Processing};
    std::optional<std::string> failureCode;
    std::optional<std::string> failureMessage;
    bool terminal{};
};

template <typename Value> struct ProviderResult
{
    ProviderTransportOutcome outcome{ProviderTransportOutcome::RetryableError};
    std::optional<Value> value;
    std::string safeError;
};

struct CreatePaymentRequest
{
    std::string attemptId;
    std::string orderId;
    std::int64_t amount{};
    std::string currency;
};

struct RetrievePaymentRequest : CreatePaymentRequest
{
    std::string providerPaymentId;
};

struct CreateRefundRequest
{
    std::string refundId;
    std::string orderId;
    std::string providerPaymentId;
    std::int64_t amount{};
};

class PaymentProvider
{
  public:
    using PaymentCompletion = std::function<void(ProviderResult<ProviderPayment>)>;
    using RefundCompletion = std::function<void(ProviderResult<ProviderRefund>)>;
    virtual ~PaymentProvider() = default;
    virtual std::string name() const = 0;
    virtual std::optional<double> scheduledDelaySeconds() const { return std::nullopt; }
    virtual void createOrRecoverPayment(CreatePaymentRequest request,
                                        PaymentCompletion completion) = 0;
    virtual void retrievePayment(RetrievePaymentRequest request,
                                 PaymentCompletion completion) = 0;
    virtual void createOrRecoverRefund(CreateRefundRequest request,
                                       RefundCompletion completion) = 0;
    virtual void retrieveRefund(std::string providerRefundId,
                                RefundCompletion completion) = 0;
};

class PaymentProviderFactory
{
  public:
    static void validateConfiguration();
    static std::shared_ptr<PaymentProvider> create();
    static std::shared_ptr<PaymentProvider> createNamed(const std::string &provider);
    static std::string configuredProvider();
    static std::string configuredCurrency();
};
}  // namespace ticketing
