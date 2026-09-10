#include "observability/Phase14Metrics.h"
#include <drogon/plugins/PromExporter.h>
#include <drogon/utils/monitoring/Gauge.h>
#include <drogon/utils/monitoring/Histogram.h>
#include <drogon/utils/monitoring/Counter.h>
#include <array>

namespace ticketing
{
namespace
{
using Gauge = drogon::monitoring::Gauge;
using Histogram = drogon::monitoring::Histogram;
using Counter = drogon::monitoring::Counter;
constexpr std::array<const char *, 8> flows{"auth","seat_read","checkout","reservation","order","payment_control","refund","other"};
constexpr std::array<const char *, 8> clients{"seat_holds","seat_holds","auth_sessions","auth_sessions","auth_sessions","auth_sessions","auth_sessions","auth_sessions"};
constexpr std::array<const char *, 8> operations{"hold_write","hold_read","auth_read","auth_write","auth_delete","login_check","login_failure","login_clear"};
constexpr std::array<const char *, 5> outcomes{"success","empty","error","timeout","abandoned"};
const std::vector<double> buckets{0.001,0.005,0.01,0.05,0.1,0.5,1,2,3,5,10,30};
struct State
{
    std::array<std::shared_ptr<ObservationSeries>,8> http, tx, redis;
    std::array<std::shared_ptr<Counter>,4> expiryItems;
    std::array<std::shared_ptr<Histogram>,2> expiryDuration;
};
std::atomic<State *> active{nullptr};

std::shared_ptr<ObservationSeries> series(drogon::plugin::PromExporter *exporter, const std::string &prefix,
    const std::vector<std::string> &labels, bool highWater, bool oldest, bool timeouts, bool duration)
{
    auto flight=exporter->getCollector<Gauge>(prefix+"_in_flight")->metric(labels);
    auto high=highWater ? exporter->getCollector<Gauge>(prefix+"_in_flight_high_water")->metric(labels) : nullptr;
    auto age=oldest ? exporter->getCollector<Gauge>(prefix+"_oldest_seconds")->metric(labels) : nullptr;
    auto timeout=timeouts ? exporter->getCollector<Counter>("ticketing_redis_operation_timeouts_total")->metric(labels) : nullptr;
    std::array<std::shared_ptr<Histogram>,5> times{};
    if (duration) for (std::size_t i=0;i<outcomes.size();++i) {
        auto values=labels; values.emplace_back(outcomes[i]);
        const auto name=prefix=="ticketing_redis_operations" ? "ticketing_redis_operation_duration_seconds" : prefix+"_duration_seconds";
        times[i]=exporter->getCollector<Histogram>(name)->metric(values,buckets,std::chrono::duration<double>{0},1);
    }
    flight->set(0); if(high) high->set(0); if(age) age->set(0);
    return std::make_shared<ObservationSeries>([flight,high,age,timeout,times](double n,double h,double a,double elapsed,ObservationOutcome outcome,bool done) {
        flight->set(n); if(high) high->set(h); if(age) age->set(a);
        if(done && times[static_cast<std::size_t>(outcome)]) times[static_cast<std::size_t>(outcome)]->observe(elapsed);
        if(done && timeout && outcome==ObservationOutcome::Timeout) timeout->increment();
    });
}
std::size_t flowFor(std::string_view route)
{
    if(route.starts_with("/auth/")) return 0;
    if(route=="/sessions/{sessionId}/seats" || route=="/sessions/{sessionId}/seat-layout" || route=="/sessions/{sessionId}/seat-availability") return 1;
    if(route.starts_with("/checkout-sessions")) return 2;
    if(route=="/reservations") return 3;
    if(route.find("refund")!=std::string_view::npos) return 6;
    if(route=="/orders/{orderId}/pay" || route.starts_with("/payment-attempts") || route.starts_with("/webhooks/")) return 5;
    if(route.starts_with("/orders")) return 4;
    return 7;
}
}

void Phase14Metrics::registerWithApplication()
{
    if(!drogon::app().getCustomConfig()["performance_metrics"]["phase14"].asBool()) return;
    auto state=std::make_shared<State>();
    drogon::app().registerBeginningAdvice([state] {
        auto *exporter=drogon::app().getPlugin<drogon::plugin::PromExporter>();
        for(std::size_t i=0;i<flows.size();++i) {
            state->http[i]=series(exporter,"ticketing_flow_requests",{flows[i]},true,false,false,false);
            state->tx[i]=series(exporter,"ticketing_db_transaction_acquire",{flows[i]},false,true,false,true);
            state->redis[i]=series(exporter,"ticketing_redis_operations",{clients[i],operations[i]},false,false,true,true);
        }
        for(std::size_t i=0;i<4;++i) state->expiryItems[i]=exporter->getCollector<Counter>("ticketing_order_expiry_items_total")->metric({std::array<const char*,4>{"scanned","expired","skipped","failed"}[i]});
        for(std::size_t i=0;i<2;++i) state->expiryDuration[i]=exporter->getCollector<Histogram>("ticketing_order_expiry_round_duration_seconds")->metric({i ? "failed" : "success"},buckets,std::chrono::duration<double>{0},1);
        auto lag=exporter->getCollector<Gauge>("ticketing_main_event_loop_lag_seconds")->metric({});
        auto high=exporter->getCollector<Gauge>("ticketing_main_event_loop_lag_high_water_seconds")->metric({});
        lag->set(0);high->set(0);
        active.store(state.get(),std::memory_order_release);
        drogon::app().getLoop()->runEvery(1.0,[state,lag,high,last=ObservationSeries::Clock::now(),peak=0.0]() mutable {
            const auto now=ObservationSeries::Clock::now();
            const auto delay=std::max(0.0,std::chrono::duration<double>(now-last).count()-1.0);
            last=now;peak=std::max(peak,delay);lag->set(delay);high->set(peak);
            for(const auto &item:state->tx) item->sample();
        });
    });
    drogon::app().registerPostRoutingAdvice([state](const drogon::HttpRequestPtr &request) {
        const auto route=request->getMatchedPathPattern();
        if(route=="/health" || route=="/metrics") return;
        request->attributes()->insert("phase14.flow",std::make_shared<AsyncObservation>(state->http[flowFor(route)]));
    });
    drogon::app().registerPreSendingAdvice([](const drogon::HttpRequestPtr &request,const drogon::HttpResponsePtr &) {
        auto observation=request->attributes()->get<std::shared_ptr<AsyncObservation>>("phase14.flow");
        if(observation) observation->finish();
    });
}
std::shared_ptr<AsyncObservation> Phase14Metrics::transaction(Flow flow)
{
    auto *state=active.load(std::memory_order_acquire);
    return state ? std::make_shared<AsyncObservation>(state->tx.at(static_cast<std::size_t>(flow))) : nullptr;
}
std::shared_ptr<AsyncObservation> Phase14Metrics::redis(RedisOperation operation)
{
    auto *state=active.load(std::memory_order_acquire);
    return state ? std::make_shared<AsyncObservation>(state->redis.at(static_cast<std::size_t>(operation))) : nullptr;
}
void Phase14Metrics::expiry(double seconds,std::size_t scanned,std::size_t expired,std::size_t skipped,std::size_t failed)
{
    if(auto *state=active.load(std::memory_order_acquire)) {
        const std::array<std::size_t,4> counts{scanned,expired,skipped,failed};
        for(std::size_t i=0;i<counts.size();++i) state->expiryItems[i]->increment(counts[i]);
        state->expiryDuration[failed ? 1 : 0]->observe(seconds);
    }
}
} // namespace ticketing
