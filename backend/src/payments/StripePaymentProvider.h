#pragma once

#include "payments/PaymentProvider.h"
#include "payments/StripeConfig.h"

#include <drogon/HttpClient.h>

namespace ticketing
{
class StripePaymentProvider final : public PaymentProvider
{
  public:
    explicit StripePaymentProvider(StripeConfig config);
    std::string name() const override { return "stripe"; }
    double processingGraceSeconds() const override { return config_.processingGraceSeconds; }
    void createOrRecoverPayment(CreatePaymentRequest request,
                                PaymentCompletion completion) override;
    void retrievePayment(RetrievePaymentRequest request,
                         PaymentCompletion completion) override;
    void createOrRecoverRefund(CreateRefundRequest request,
                               RefundCompletion completion) override;
    void retrieveRefund(RetrieveRefundRequest request,
                        RefundCompletion completion) override;

  private:
    using JsonCompletion = std::function<void(ProviderTransportOutcome,
                                               const Json::Value *,
                                               std::string)>;
    void request(drogon::HttpMethod method, std::string path, std::string body,
                 std::optional<std::string> idempotencyKey,
                 JsonCompletion completion) const;
    static ProviderResult<ProviderPayment> mapPayment(
        const Json::Value &json, const CreatePaymentRequest &expected);
    static ProviderResult<ProviderRefund> mapRefund(const Json::Value &json,
                                                   const CreateRefundRequest &expected);

    StripeConfig config_;
    drogon::HttpClientPtr client_;
};
}  // namespace ticketing
