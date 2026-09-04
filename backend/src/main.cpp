#include "workers/OrderExpiryWorker.h"
#include "services/CheckoutSessionService.h"
#include "services/SeatHoldService.h"
#include "services/PaymentSimulation.h"
#include "security/AuthConfig.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>

#include <cstddef>
#include <exception>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

namespace
{
constexpr std::size_t kDefaultOrderExpiryBatchSize = 100;
constexpr double kDefaultOrderExpiryIntervalSeconds = 5.0;
constexpr std::size_t kDefaultCheckoutReconciliationBatchSize = 100;

std::pair<std::size_t, double> loadOrderExpiryWorkerConfig()
{
    auto batchSize = kDefaultOrderExpiryBatchSize;
    auto intervalSeconds = kDefaultOrderExpiryIntervalSeconds;
    const auto &config =
        drogon::app().getCustomConfig()["order_expiry_worker"];

    if (config.isNull())
    {
        return {batchSize, intervalSeconds};
    }
    if (!config.isObject())
    {
        throw std::invalid_argument(
            "custom_config.order_expiry_worker must be an object");
    }

    if (config.isMember("batch_size"))
    {
        const auto &value = config["batch_size"];
        if (!value.isUInt64() || value.asUInt64() == 0 ||
            value.asUInt64() > std::numeric_limits<std::size_t>::max())
        {
            throw std::invalid_argument(
                "order_expiry_worker.batch_size must be a positive integer");
        }
        batchSize = static_cast<std::size_t>(value.asUInt64());
    }

    if (config.isMember("interval_seconds"))
    {
        const auto &value = config["interval_seconds"];
        if (!value.isNumeric() || value.asDouble() <= 0.0)
        {
            throw std::invalid_argument(
                "order_expiry_worker.interval_seconds must be positive");
        }
        intervalSeconds = value.asDouble();
    }

    return {batchSize, intervalSeconds};
}

std::size_t loadCheckoutReconciliationBatchSize()
{
    auto batchSize = kDefaultCheckoutReconciliationBatchSize;
    const auto &config =
        drogon::app().getCustomConfig()["checkout_session_reconciliation"];
    if (config.isNull())
    {
        return batchSize;
    }
    if (!config.isObject())
    {
        throw std::invalid_argument(
            "custom_config.checkout_session_reconciliation must be an object");
    }
    if (config.isMember("batch_size"))
    {
        const auto &value = config["batch_size"];
        if (!value.isUInt64() || value.asUInt64() == 0 ||
            value.asUInt64() > std::numeric_limits<std::size_t>::max())
        {
            throw std::invalid_argument(
                "checkout_session_reconciliation.batch_size must be a positive integer");
        }
        batchSize = static_cast<std::size_t>(value.asUInt64());
    }
    return batchSize;
}
}  // namespace

int main(int argc, char *argv[])
{
    const std::string configPath =
        argc > 1 ? argv[1] : "config/config.json";

    try
    {
        drogon::app().loadConfigFile(configPath);
        ticketing::SeatHoldService::validateConfiguration();
        ticketing::PaymentSimulation::validateConfiguration();
        ticketing::AuthConfig::validate();
        ticketing::PerformanceMetrics::registerWithApplication();
        const auto [batchSize, intervalSeconds] =
            loadOrderExpiryWorkerConfig();
        const auto checkoutReconciliationBatchSize =
            loadCheckoutReconciliationBatchSize();
        auto expiryWorker = std::make_shared<ticketing::OrderExpiryWorker>(
            batchSize, intervalSeconds);
        auto checkoutReconciliation =
            std::make_shared<ticketing::CheckoutSessionService>();
        drogon::app().registerBeginningAdvice(
            [expiryWorker,
             checkoutReconciliation,
             checkoutReconciliationBatchSize] {
                expiryWorker->start();
                checkoutReconciliation->reconcileSubmitting(
                    checkoutReconciliationBatchSize,
                    [checkoutReconciliation](std::size_t repaired,
                                             bool succeeded) {
                        if (!succeeded)
                        {
                            LOG_ERROR << "Checkout session startup "
                                         "reconciliation failed";
                        }
                        else if (repaired > 0)
                        {
                            LOG_INFO << "Checkout session startup "
                                        "reconciliation repaired "
                                     << repaired << " session(s)";
                        }
                    });
            });
        LOG_INFO << "Starting ticketing backend with config: " << configPath;
        drogon::app().run();
    }
    catch (const std::exception &error)
    {
        LOG_FATAL << "Backend startup failed: " << error.what();
        return 1;
    }

    return 0;
}
