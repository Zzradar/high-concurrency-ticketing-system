#include "observability/PerformanceMetrics.h"
#include <chrono>
#include "workers/SeatAvailabilityProjectionWorker.h"
#include <array>
#include <cstdlib>
#include <functional>
#include <utility>
#include <vector>

namespace ticketing
{
namespace
{
struct ProjectionRound : std::enable_shared_from_this<ProjectionRound>
{
    using Event=std::array<std::string,5>;
    std::vector<Event> events;
    std::size_t index{0};
    std::string token;
    std::function<void()> done;
    void next()
    {
        if(index==events.size()){done();return;}
        const auto event=events[index++];
        auto self=shared_from_this();
        SeatAvailabilityReadModel::apply(event[1],event[2],event[3],event[4],
            [self,event](SeatAvailabilityReadModel::Strings result){
                const auto &outcome=result.front();
                PerformanceMetrics::availability("projector",outcome);
                if(outcome=="APPLIED")
                {
                    // Explicit opt-in fault gate, only for isolated integration processes.
                    const auto *fault=std::getenv("PHASE16_FAULT_AFTER_REDIS_APPLY");
                    if(fault && std::string_view(fault)=="1")std::_Exit(86);
                }
                if(outcome=="APPLIED" || outcome=="STALE_OR_DUPLICATE" || outcome=="NO_MODEL")
                    self->finishEvent(event[0],true);
                else if(outcome=="INITIALIZING")self->finishEvent(event[0],false);
                else self->next(); // Leave the lease/event intact for retry after expiry.
            });
    }
    void finishEvent(const std::string &id,bool remove)
    {
        auto self=shared_from_this();
        const char *sql=remove ? "DELETE FROM seat_availability_outbox WHERE id=$1::bigint AND lease_token=$2" :
            "UPDATE seat_availability_outbox SET lease_token=NULL,lease_until=NULL WHERE id=$1::bigint AND lease_token=$2";
        drogon::app().getDbClient()->execSqlAsync(sql,
            [self](const drogon::orm::Result &){self->next();},
            [self](const drogon::orm::DrogonDbException &){self->next();},id,token);
    }
};
}
void SeatAvailabilityProjectionWorker::start()
{
    if(started_)return;
    started_=true;
    run();
}
void SeatAvailabilityProjectionWorker::run()
{
    auto weak=weak_from_this();
    const auto token=drogon::utils::getUuid();
    const auto started=std::chrono::steady_clock::now();
    drogon::app().getDbClient()->execSqlAsync(R"SQL(
        WITH candidates AS (
            SELECT id FROM seat_availability_outbox
            WHERE lease_until IS NULL OR lease_until<=CURRENT_TIMESTAMP
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $1::integer
        )
        UPDATE seat_availability_outbox event
        SET lease_token=$2,lease_until=CURRENT_TIMESTAMP+($3::double precision*interval '1 second')
        FROM candidates WHERE event.id=candidates.id
        RETURNING event.id,event.session_id,event.session_seat_id,event.formal_status,event.formal_version
    )SQL",[weak,token,started](const drogon::orm::Result &result){
        auto round=std::make_shared<ProjectionRound>();round->token=token;
        for(const auto &r:result)round->events.push_back({r["id"].as<std::string>(),r["session_id"].as<std::string>(),
            r["session_seat_id"].as<std::string>(),r["formal_status"].as<std::string>(),r["formal_version"].as<std::string>()});
        round->done=[weak,started]{PerformanceMetrics::availability("projector_round","ok",std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count());if(auto self=weak.lock())self->schedule();};round->next();
    },[weak](const drogon::orm::DrogonDbException &){if(auto self=weak.lock())self->schedule();},
    config_.projectionBatchSize,token,config_.projectionLeaseSeconds);
}
void SeatAvailabilityProjectionWorker::schedule()
{
    auto weak=weak_from_this();
    drogon::app().getLoop()->runAfter(config_.projectionIntervalSeconds,[weak]{if(auto self=weak.lock())self->run();});
}
}
