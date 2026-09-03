#include "services/PaymentSimulation.h"

#include <drogon/drogon.h>

#include <cstdlib>
#include <random>
#include <stdexcept>
#include <string_view>

namespace ticketing
{
PaymentSimulationConfig PaymentSimulation::loadConfiguration()
{
    PaymentSimulationConfig result;
    const auto &config = drogon::app().getCustomConfig()["payment_simulation"];
    if (!config.isObject())
        throw std::invalid_argument("custom_config.payment_simulation must be an object");
    auto read = [&config](const char *name) {
        if (!config.isMember(name) || !config[name].isNumeric())
            throw std::invalid_argument(std::string{"payment_simulation."} + name + " must be numeric");
        return config[name].asDouble();
    };
    result.minDelaySeconds = read("min_delay_seconds");
    result.maxDelaySeconds = read("max_delay_seconds");
    result.failureRate = read("failure_rate");
    result.processingGraceSeconds = read("processing_grace_seconds");
    if (result.minDelaySeconds <= 0.0 ||
        result.maxDelaySeconds < result.minDelaySeconds ||
        result.failureRate < 0.0 || result.failureRate > 1.0 ||
        result.processingGraceSeconds <= result.maxDelaySeconds)
        throw std::invalid_argument("payment_simulation values violate delay, rate, or grace constraints");
    return result;
}

void PaymentSimulation::validateConfiguration()
{
    (void)loadConfiguration();
}

PaymentSimulationDecision PaymentSimulation::decide(
    const PaymentSimulationConfig &config)
{
    thread_local std::mt19937_64 generator{std::random_device{}()};
    std::uniform_real_distribution<double> delay(config.minDelaySeconds,
                                                  config.maxDelaySeconds);
    std::bernoulli_distribution failure(config.failureRate);
    bool succeeded = !failure(generator);
    if (const char *forced = std::getenv("TICKETING_PAYMENT_FORCE_OUTCOME"))
    {
        const std::string_view value{forced};
        if (value == "SUCCESS") succeeded = true;
        else if (value == "FAILURE") succeeded = false;
        else if (!value.empty())
            throw std::invalid_argument("TICKETING_PAYMENT_FORCE_OUTCOME must be SUCCESS or FAILURE");
    }
    return {.delaySeconds = delay(generator), .succeeded = succeeded};
}
}  // namespace ticketing
