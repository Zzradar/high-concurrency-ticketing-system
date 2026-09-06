#include "observability/PerformanceMetrics.h"

#include "security/PasswordHashExecutor.h"

#include <drogon/drogon.h>
#include <drogon/plugins/PromExporter.h>
#include <drogon/utils/monitoring/Counter.h>
#include <drogon/utils/monitoring/Gauge.h>
#include <drogon/utils/monitoring/Histogram.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
using CounterCollector =
    drogon::monitoring::Collector<drogon::monitoring::Counter>;
using GaugeCollector =
    drogon::monitoring::Collector<drogon::monitoring::Gauge>;
using HistogramCollector =
    drogon::monitoring::Collector<drogon::monitoring::Histogram>;

constexpr char kStartedAtAttribute[] = "ticketing.metrics.started_at";
constexpr char kCompletedAttribute[] = "ticketing.metrics.completed";
constexpr char kUnmatchedRoute[] = "__unmatched__";

const std::vector<double> kDurationBuckets{
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1,
    0.25,  0.5,    1.0,   2.5,  5.0,   10.0,
};

const std::vector<double> kPasswordHashDurationBuckets{
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1,
    0.25,  0.5,    1.0,   2.5,  5.0,   10.0, 30.0,
};

struct MetricsState
{
    std::shared_ptr<CounterCollector> requests;
    std::shared_ptr<HistogramCollector> durations;
    std::shared_ptr<GaugeCollector> inFlight;
    std::shared_ptr<GaugeCollector> passwordHashQueueDepth;
    std::shared_ptr<GaugeCollector> passwordHashActiveWorkers;
    std::shared_ptr<CounterCollector> passwordHashSubmissions;
    std::shared_ptr<HistogramCollector> passwordHashQueueWait;
    std::shared_ptr<HistogramCollector> passwordHashExecution;
};

std::mutex passwordHashObserverMutex;
std::shared_ptr<ticketing::PasswordHashObserver> passwordHashObserverSink;

class PasswordHashMetricsObserver final
    : public ticketing::PasswordHashObserver
{
  public:
    explicit PasswordHashMetricsObserver(std::shared_ptr<MetricsState> state)
        : state_(std::move(state))
    {
    }

    void onSubmission(bool accepted, std::size_t queueDepth) noexcept override
    {
        state_->passwordHashSubmissions
            ->metric({accepted ? "accepted" : "rejected"})
            ->increment();
        state_->passwordHashQueueDepth->metric({})->set(queueDepth);
    }

    void onExecutionStarted(std::size_t queueDepth,
                            std::size_t activeWorkers,
                            double queueWaitSeconds) noexcept override
    {
        state_->passwordHashQueueDepth->metric({})->set(queueDepth);
        state_->passwordHashActiveWorkers->metric({})->set(activeWorkers);
        state_->passwordHashQueueWait
            ->metric({}, kPasswordHashDurationBuckets,
                     std::chrono::duration<double>{0}, 1)
            ->observe(queueWaitSeconds);
    }

    void onExecutionFinished(std::size_t activeWorkers,
                             double executionSeconds) noexcept override
    {
        state_->passwordHashActiveWorkers->metric({})->set(activeWorkers);
        state_->passwordHashExecution
            ->metric({}, kPasswordHashDurationBuckets,
                     std::chrono::duration<double>{0}, 1)
            ->observe(executionSeconds);
    }

  private:
    std::shared_ptr<MetricsState> state_;
};

bool isExcluded(const drogon::HttpRequestPtr &request)
{
    const auto &path = request->path();
    return path == "/health" || path == "/metrics";
}

std::string statusClass(drogon::HttpStatusCode status)
{
    const auto code = static_cast<int>(status);
    if (code >= 100 && code < 600)
    {
        return std::to_string(code / 100) + "xx";
    }
    return "unknown";
}

std::string normalizedRoute(const drogon::HttpRequestPtr &request)
{
    const auto pattern = request->getMatchedPathPattern();
    return pattern.empty() ? kUnmatchedRoute : std::string{pattern};
}
}  // namespace

namespace ticketing
{
void PerformanceMetrics::registerWithApplication()
{
    const auto &config =
        drogon::app().getCustomConfig()["performance_metrics"];
    if (config.isNull())
    {
        return;
    }
    if (!config.isObject() || !config["enabled"].isBool())
    {
        throw std::invalid_argument(
            "custom_config.performance_metrics.enabled must be a boolean");
    }
    if (!config["enabled"].asBool())
    {
        return;
    }

    auto state = std::make_shared<MetricsState>();
    drogon::app().registerBeginningAdvice([state] {
        auto *exporter =
            drogon::app().getPlugin<drogon::plugin::PromExporter>();
        if (exporter == nullptr)
        {
            throw std::runtime_error(
                "PromExporter must be configured when performance metrics are enabled");
        }
        state->requests = exporter->getCollector<drogon::monitoring::Counter>(
            "ticketing_http_requests_total");
        state->durations =
            exporter->getCollector<drogon::monitoring::Histogram>(
                "ticketing_http_request_duration_seconds");
        state->inFlight = exporter->getCollector<drogon::monitoring::Gauge>(
            "ticketing_http_requests_in_flight");
        state->passwordHashQueueDepth =
            exporter->getCollector<drogon::monitoring::Gauge>(
                "ticketing_password_hash_queue_depth");
        state->passwordHashActiveWorkers =
            exporter->getCollector<drogon::monitoring::Gauge>(
                "ticketing_password_hash_active_workers");
        state->passwordHashSubmissions =
            exporter->getCollector<drogon::monitoring::Counter>(
                "ticketing_password_hash_submissions_total");
        state->passwordHashQueueWait =
            exporter->getCollector<drogon::monitoring::Histogram>(
                "ticketing_password_hash_queue_wait_seconds");
        state->passwordHashExecution =
            exporter->getCollector<drogon::monitoring::Histogram>(
                "ticketing_password_hash_execution_seconds");
        if (!state->requests || !state->durations || !state->inFlight ||
            !state->passwordHashQueueDepth ||
            !state->passwordHashActiveWorkers ||
            !state->passwordHashSubmissions || !state->passwordHashQueueWait ||
            !state->passwordHashExecution)
        {
            throw std::runtime_error(
                "performance metric collector types do not match their configuration");
        }
        state->inFlight->metric({})->set(0.0);
        state->passwordHashQueueDepth->metric({})->set(0.0);
        state->passwordHashActiveWorkers->metric({})->set(0.0);
        {
            std::lock_guard lock{passwordHashObserverMutex};
            passwordHashObserverSink =
                std::make_shared<PasswordHashMetricsObserver>(state);
        }
    });

    drogon::app().registerPreRoutingAdvice(
        [state](const drogon::HttpRequestPtr &request) {
            if (isExcluded(request))
            {
                return;
            }
            request->attributes()->insert(
                kStartedAtAttribute, std::chrono::steady_clock::now());
            request->attributes()->insert(
                kCompletedAttribute, std::make_shared<std::atomic_bool>(false));
            state->inFlight->metric({})->increment();
        });

    drogon::app().registerPreSendingAdvice(
        [state](const drogon::HttpRequestPtr &request,
                const drogon::HttpResponsePtr &response) {
            if (isExcluded(request))
            {
                return;
            }
            const auto completed = request->attributes()->get<
                std::shared_ptr<std::atomic_bool>>(kCompletedAttribute);
            if (!completed || completed->exchange(true))
            {
                return;
            }

            const auto startedAt =
                request->attributes()->get<std::chrono::steady_clock::time_point>(
                    kStartedAtAttribute);
            const auto elapsed = std::chrono::duration<double>(
                                     std::chrono::steady_clock::now() - startedAt)
                                     .count();
            const std::vector<std::string> labels{
                request->methodString(),
                normalizedRoute(request),
                statusClass(response->statusCode()),
            };
            state->requests->metric(labels)->increment();
            state->durations
                ->metric(labels,
                         kDurationBuckets,
                         std::chrono::duration<double>{0},
                         1)
                ->observe(elapsed);
            state->inFlight->metric({})->decrement();
        });
}

std::shared_ptr<PasswordHashObserver>
PerformanceMetrics::passwordHashObserver()
{
    std::lock_guard lock{passwordHashObserverMutex};
    return passwordHashObserverSink;
}
}  // namespace ticketing
