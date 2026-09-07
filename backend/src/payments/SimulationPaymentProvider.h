#pragma once

#include "payments/PaymentProvider.h"
#include "services/PaymentSimulation.h"

namespace ticketing
{
class SimulationPaymentProvider final : public PaymentProvider
{
  public:
    SimulationPaymentProvider();
    std::string name() const override { return "simulation"; }
    double processingGraceSeconds() const override { return config_.processingGraceSeconds; }
    std::optional<double> scheduledDelaySeconds() const override;
    void createOrRecoverPayment(CreatePaymentRequest request,
                                PaymentCompletion completion) override;
    void retrievePayment(RetrievePaymentRequest request,
                         PaymentCompletion completion) override;
    void createOrRecoverRefund(CreateRefundRequest request,
                               RefundCompletion completion) override;
    void retrieveRefund(RetrieveRefundRequest request,
                        RefundCompletion completion) override;

  private:
    PaymentSimulationConfig config_;
    PaymentSimulationDecision decision_;
};
}  // namespace ticketing
