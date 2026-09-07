#include "workers/OrderExpiryWorker.h"
#include "workers/PaymentReconciliationWorker.h"
#include "services/CheckoutSessionService.h"
#include "services/SeatHoldService.h"
#include "services/SeatService.h"
#include "payments/PaymentProvider.h"
#include "security/AuthConfig.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>

#include <cstddef>
#include <exception>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>

namespace
{
constexpr std::size_t kDefaultOrderExpiryBatchSize = 100;
constexpr double kDefaultOrderExpiryIntervalSeconds = 5.0;
constexpr std::size_t kDefaultCheckoutReconciliationBatchSize = 100;
constexpr std::size_t kDefaultPaymentReconciliationBatchSize = 100;
constexpr double kDefaultPaymentReconciliationIntervalSeconds = 2.0;
constexpr double kDefaultPaymentReconciliationMaxBackoffSeconds = 60.0;

struct ComputeShutdown
{
    std::shared_ptr<ticketing::SeatMapComputeExecutor> executor;
    ~ComputeShutdown() { executor->shutdown(); }
};

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

std::tuple<std::size_t, double, double> loadPaymentReconciliationConfig()
{
    auto batchSize = kDefaultPaymentReconciliationBatchSize;
    auto interval = kDefaultPaymentReconciliationIntervalSeconds;
    auto maxBackoff = kDefaultPaymentReconciliationMaxBackoffSeconds;
    const auto &config = drogon::app().getCustomConfig()["payment_reconciliation"];
    if (config.isNull()) return {batchSize, interval, maxBackoff};
    if (!config.isObject())
        throw std::invalid_argument("custom_config.payment_reconciliation must be an object");
    if (config.isMember("batch_size"))
    {
        if (!config["batch_size"].isUInt64() || config["batch_size"].asUInt64() == 0)
            throw std::invalid_argument("payment_reconciliation.batch_size must be positive");
        batchSize = static_cast<std::size_t>(config["batch_size"].asUInt64());
    }
    if (config.isMember("interval_seconds")) interval = config["interval_seconds"].asDouble();
    if (config.isMember("max_backoff_seconds")) maxBackoff = config["max_backoff_seconds"].asDouble();
    if (interval <= 0 || maxBackoff <= 0)
        throw std::invalid_argument("payment reconciliation intervals must be positive");
    return {batchSize, interval, maxBackoff};
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
        ticketing::PaymentProviderFactory::validateConfiguration();
        ticketing::AuthConfig::validate();
        ticketing::PerformanceMetrics::registerWithApplication();
        const auto &computeConfig = drogon::app().getCustomConfig();
        const auto &computeWorkers = computeConfig["seat_map_compute_workers"];
        const auto &computeCapacity = computeConfig["seat_map_compute_queue_capacity"];
        if ((!computeWorkers.isNull() && !computeWorkers.isUInt()) ||
            (!computeCapacity.isNull() && !computeCapacity.isUInt()))
            throw std::invalid_argument("seat map compute settings must be unsigned integers");
        auto seatMapCompute = std::make_shared<ticketing::SeatMapComputeExecutor>(
            computeWorkers.isNull() ? 4 : computeWorkers.asUInt(),
            computeCapacity.isNull() ? 16 : computeCapacity.asUInt(),
            ticketing::PerformanceMetrics::seatMapComputeObserver());
        ticketing::SeatService::configureComputeExecutor(seatMapCompute);
        ComputeShutdown computeShutdown{seatMapCompute};
        const auto [batchSize, intervalSeconds] =
            loadOrderExpiryWorkerConfig();
        const auto checkoutReconciliationBatchSize =
            loadCheckoutReconciliationBatchSize();
        auto expiryWorker = std::make_shared<ticketing::OrderExpiryWorker>(
            batchSize, intervalSeconds);
        const auto [paymentBatchSize, paymentInterval, paymentMaxBackoff] =
            loadPaymentReconciliationConfig();
        auto paymentWorker = std::make_shared<ticketing::PaymentReconciliationWorker>(
            paymentBatchSize, paymentInterval, paymentMaxBackoff);
        auto checkoutReconciliation =
            std::make_shared<ticketing::CheckoutSessionService>();
        drogon::app().registerBeginningAdvice(
            [expiryWorker,
             checkoutReconciliation,
             paymentWorker,
             checkoutReconciliationBatchSize] {
                expiryWorker->start();
                paymentWorker->start();
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
        // Join before application/static teardown. Accepted tasks drain;
        // late Redis callbacks retain the stopped executor and receive busy.
        seatMapCompute->shutdown();
    }
    catch (const std::exception &error)
    {
        LOG_FATAL << "Backend startup failed: " << error.what();
        return 1;
    }

    return 0;
}
