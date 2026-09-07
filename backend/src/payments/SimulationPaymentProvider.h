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
    std::optional<double> scheduledDelaySeconds() const override;
    void createOrRecoverPayment(CreatePaymentRequest request,
                                PaymentCompletion completion) override;
    void retrievePayment(RetrievePaymentRequest request,
                         PaymentCompletion completion) override;
    void createOrRecoverRefund(CreateRefundRequest request,
                               RefundCompletion completion) override;
    void retrieveRefund(std::string providerRefundId,
                        RefundCompletion completion) override;

  private:
    PaymentSimulationDecision decision_;
};
}  // namespace ticketing
