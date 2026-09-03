#pragma once

#include <string>

namespace ticketing
{
struct PaymentSimulationConfig
{
    double minDelaySeconds{2.0};
    double maxDelaySeconds{6.0};
    double failureRate{0.01};
    double processingGraceSeconds{10.0};
};

struct PaymentSimulationDecision
{
    double delaySeconds{};
    bool succeeded{};
};

class PaymentSimulation
{
  public:
    static PaymentSimulationConfig loadConfiguration();
    static void validateConfiguration();
    static PaymentSimulationDecision decide(const PaymentSimulationConfig &config);
};
}  // namespace ticketing
