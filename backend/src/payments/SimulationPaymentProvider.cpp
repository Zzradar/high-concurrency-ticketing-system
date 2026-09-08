#include "payments/SimulationPaymentProvider.h"

#include <drogon/drogon.h>

namespace ticketing
{
SimulationPaymentProvider::SimulationPaymentProvider()
    : config_(PaymentSimulation::loadConfiguration()),
      decision_(PaymentSimulation::decide(config_))
{
}

std::optional<double> SimulationPaymentProvider::scheduledDelaySeconds() const
{
    return decision_.delaySeconds;
}

void SimulationPaymentProvider::createOrRecoverPayment(
    CreatePaymentRequest request, PaymentCompletion completion)
{
    auto processing = ProviderPayment{.provider = name(),
                                      .providerPaymentId = "sim-" + request.attemptId,
                                      .providerStatus = "processing"};
    completion({ProviderTransportOutcome::Success, processing, {}});
    const auto decision = decision_;
    drogon::app().getLoop()->runAfter(decision.delaySeconds,
        [request = std::move(request), completion = std::move(completion), decision] {
            ProviderPayment payment{.provider = "simulation",
                                    .providerPaymentId = "sim-" + request.attemptId,
                                    .providerStatus = decision.succeeded ? "succeeded" : "failed",
                                    .mappedState = decision.succeeded
                                                       ? ProviderPaymentState::Succeeded
                                                       : ProviderPaymentState::Failed,
                                    .terminal = true};
            if (!decision.succeeded)
                payment.failureCode = "SIMULATED_PAYMENT_FAILURE";
            completion({ProviderTransportOutcome::Success, std::move(payment), {}});
        });
}

void SimulationPaymentProvider::retrievePayment(
    RetrievePaymentRequest request, PaymentCompletion completion)
{
    createOrRecoverPayment(std::move(request), std::move(completion));
}

void SimulationPaymentProvider::createOrRecoverRefund(
    CreateRefundRequest request, RefundCompletion completion)
{
    ProviderRefund refund{.provider = name(),
                          .providerRefundId = "sim-" + request.refundId,
                          .providerStatus = "succeeded",
                          .mappedState = ProviderRefundState::Succeeded,
                          .terminal = true};
    refund.providerPaymentId = request.providerPaymentId;
    refund.localRefundId = request.refundId;
    refund.orderId = request.orderId;
    refund.amount = request.amount;
    refund.currency = request.currency;
    drogon::app().getLoop()->queueInLoop(
        [completion = std::move(completion), refund = std::move(refund)]() mutable {
            completion({ProviderTransportOutcome::Success, std::move(refund), {}});
        });
}

void SimulationPaymentProvider::retrieveRefund(
    RetrieveRefundRequest request, RefundCompletion completion)
{
    ProviderRefund refund{.provider = name(),
                          .providerRefundId = std::move(request.providerRefundId),
                          .providerStatus = "succeeded",
                          .mappedState = ProviderRefundState::Succeeded,
                          .terminal = true};
    refund.providerPaymentId = request.providerPaymentId;
    refund.localRefundId = request.refundId;
    refund.orderId = request.orderId;
    refund.amount = request.amount;
    refund.currency = request.currency;
    completion({ProviderTransportOutcome::Success, std::move(refund), {}});
}
}  // namespace ticketing
