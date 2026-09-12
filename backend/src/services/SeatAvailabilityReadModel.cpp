#include "admission/AdmissionMetrics.h"
#include "common/SeatReadConfig.h"
#include "observability/PerformanceMetrics.h"
#include <cstdlib>
#include "services/SeatAvailabilityReadModel.h"
#include "availability/AvailabilityScripts.h"
#include "common/ApiResponse.h"
#include "repositories/SeatRepository.h"
#include "services/SeatDisplayStatus.h"
#include "services/SeatHoldService.h"

#include <array>
#include <atomic>
#include <charconv>
#include <chrono>
#include <cmath>
#include <limits>
#include <optional>
#include <regex>
#include <stdexcept>

namespace ticketing
{
namespace
{
std::shared_ptr<SeatMapComputeExecutor> executor;
SeatAvailabilityConfig settings;
using Strings = SeatAvailabilityReadModel::Strings;
std::string compose(std::string_view tail)
{
    return std::string(availability_scripts::common) + std::string(tail);
}
const std::string initScript = compose(availability_scripts::init);
const std::string readScript = compose(availability_scripts::read);
const std::string applyScript = compose(availability_scripts::apply);
const std::string expireScript = compose(availability_scripts::expire);
const std::string acquireScript = R"lua(
local meta=KEYS[1]..':meta'
local t=redis.call('TYPE',meta).ok
if t=='hash' and redis.call('HGET',meta,'ready')=='1' then return {'READY'} end
if t~='none' and t~='hash' then redis.call('DEL',meta) end
if redis.call('SET',KEYS[1]..':init-lock',ARGV[1],'NX','PX',ARGV[2]) then return {'WINNER'} end
return {'WAIT'}
)lua";
const std::string unlockScript = R"lua(
if redis.call('GET',KEYS[1]..':init-lock')==ARGV[1] then redis.call('DEL',KEYS[1]..':init-lock') end
return {'OK'}
)lua";

struct Request : std::enable_shared_from_this<Request>
{
    std::string session, zone, owner, generation, since, token;
    SeatAvailabilityReadModel::Reply reply;
    std::atomic_bool completed{false};
    std::chrono::steady_clock::time_point started{std::chrono::steady_clock::now()};
    bool rebuilding{false};

    void respond(const drogon::HttpResponsePtr &response)
    {
        if (!completed.exchange(true)) reply(response);
    }
    void error(const std::string &code)
    {
        auto status = drogon::k500InternalServerError;
        if (code == "SESSION_NOT_FOUND" || code == "ZONE_NOT_FOUND") status=drogon::k404NotFound;
        if (code == "SEAT_MAP_BUSY" || code == "SEAT_AVAILABILITY_INITIALIZING") status=drogon::k503ServiceUnavailable;
        respond(makeErrorResponse(status,code,code));
    }
    void compute(std::function<void()> work)
    {
        auto self=shared_from_this();
        if (!executor->trySubmit(std::move(work),[self]{self->error("INTERNAL_ERROR");})) error("SEAT_MAP_BUSY");
    }
    void acquire()
    {
        auto self=shared_from_this();
        SeatAvailabilityReadModel::eval(acquireScript,SeatAvailabilityReadModel::prefix(session),
            {token,std::to_string(settings.initLockSeconds*1000)},[self](Strings result){
                if (result[0]=="READY") self->expire();
                else if (result[0]=="WINNER") self->initialize();
                else if (result[0]=="WAIT") self->wait();
                else self->fallback();
            });
    }
    void wait()
    {
        if (std::chrono::steady_clock::now()-started >= std::chrono::milliseconds(settings.initWaitMilliseconds))
        {error("SEAT_AVAILABILITY_INITIALIZING"); return;}
        auto self=shared_from_this();
        drogon::app().getLoop()->runAfter(0.02,[self]{self->acquire();});
    }
    void initialize()
    {
        PerformanceMetrics::availability("init","winner");
        auto self=shared_from_this();
        drogon::app().getDbClient()->execSqlAsync(R"SQL(
            SELECT inventory.id,inventory.status,inventory.formal_version,zone.name AS zone
            FROM session_seats inventory JOIN seats seat ON seat.id=inventory.seat_id
            JOIN venue_zones zone ON zone.id=seat.zone_id AND zone.venue_id=seat.venue_id
            WHERE inventory.session_id=$1 ORDER BY zone.sort_order,seat.row_no,seat.seat_no,inventory.id
        )SQL",[self](const drogon::orm::Result &result){
            std::vector<std::array<std::string,4>> rows;
            rows.reserve(result.size());
            for (const auto &r:result) rows.push_back({r["id"].as<std::string>(),r["status"].as<std::string>(),
                r["formal_version"].as<std::string>(),r["zone"].as<std::string>()});
            if (rows.empty())
            {
                SeatRepository{}.sessionExists(self->session,[self](bool exists){
                    self->unlock(); self->error(exists ? "ZONE_NOT_FOUND" : "SESSION_NOT_FOUND");
                },[self]{self->unlock(); self->error("INTERNAL_ERROR");});
                return;
            }
            const auto *fault=std::getenv("PHASE16_FAULT_AFTER_PG_SNAPSHOT");
            if(fault && std::string_view(fault)=="1")std::_Exit(87);
            self->compute([self,rows=std::move(rows)]{
                Json::Value payload(Json::arrayValue);
                for (const auto &r:rows)
                {
                    Json::Value seat(Json::arrayValue);
                    for(const auto &v:r) seat.append(v);
                    payload.append(std::move(seat));
                }
                Json::StreamWriterBuilder writer; writer["indentation"]="";
                SeatAvailabilityReadModel::eval(initScript,SeatAvailabilityReadModel::prefix(self->session),
                    {self->token,drogon::utils::getUuid(),Json::writeString(writer,payload)},[self](Strings result){
                        PerformanceMetrics::availability("init",result[0],std::chrono::duration<double>(std::chrono::steady_clock::now()-self->started).count());
                        if(result[0]=="READY") self->expire();
                        else if(result[0]=="STALE_INIT") self->wait();
                        else {self->unlock(); self->fallback();}
                    });
            });
        },[self](const drogon::orm::DrogonDbException &){self->unlock(); self->error("INTERNAL_ERROR");},session);
    }
    void unlock()
    {
        SeatAvailabilityReadModel::eval(unlockScript,SeatAvailabilityReadModel::prefix(session),{token},[](Strings){});
    }
    void expire()
    {
        auto self=shared_from_this();
        SeatAvailabilityReadModel::eval(expireScript,SeatAvailabilityReadModel::prefix(session),
            {std::to_string(settings.expiryCleanupBatch),std::to_string(settings.streamMaxlen)},[self](Strings result){
                if(result[0]=="OK")
                {
                    PerformanceMetrics::availability("expiry","ok",0,std::stod(result.at(1)));
                    if(result.size()>2 && result[2]!="0")
                        drogon::app().getLoop()->runAfter(0,[self]{self->expire();});
                    else self->snapshot();
                }
                else if(result[0]=="REBUILD" && !self->rebuilding)
                {self->rebuilding=true; self->acquire();}
                else self->fallback();
            });
    }
    void snapshot()
    {
        auto self=shared_from_this();
        SeatAvailabilityReadModel::eval(readScript,SeatAvailabilityReadModel::prefix(session),
            {zone,generation,since,std::to_string(settings.deltaScanLimit)},[self](Strings result){
                if(result[0]=="ZONE_NOT_FOUND") {self->error(result[0]);return;}
                if(result[0]!="OK") {self->fallback();return;}
                self->compute([self,result=std::move(result)]{
                    Json::Value body;
                    body["sessionId"]=self->session; body["zone"]=self->zone;
                    body["mode"]=result.at(1); body["generation"]=result.at(2); body["cursor"]=result.at(3);
                    body["reset"]=result.at(4)=="1"; body["hasMore"]=result.at(5)=="1"; body["degraded"]=false;
                    body["zones"]=Json::Value(Json::arrayValue);
                    auto count=std::stoul(result.at(7)); std::size_t index=8;
                    for(std::size_t i=0;i<count;++i)
                    {
                        Json::Value zone; zone["zone"]=result.at(index++);
                        for(const auto *name:{"total","available","held","sold"}) zone[name]=Json::Int64(std::stoll(result.at(index++)));
                        body["zones"].append(std::move(zone));
                    }
                    count=std::stoul(result.at(index++));
                    const char *field=result.at(1)=="delta" ? "changes" : "seats";
                    body[field]=Json::Value(Json::arrayValue);
                    for(std::size_t i=0;i<count;++i)
                    {
                        Json::Value seat; seat["id"]=result.at(index++);
                        auto formal=result.at(index++); auto owner=result.at(index++);
                        seat["status"]=displaySeatStatus(formal,owner.empty()?std::nullopt:std::optional(owner),self->owner);
                        body[field].append(std::move(seat));
                    }
                    const auto polling=SeatReadConfig::parse(drogon::app().getCustomConfig()["seat_read"]);
                    body["pollAfterMs"]=body["hasMore"].asBool()?0:result.at(1)=="snapshot"?polling.snapshotMs:count?polling.changedMs:polling.emptyMs;
                    admission::AdmissionMetrics::gauge("ticketing_availability_poll_interval_seconds",{body["hasMore"].asBool()?"CATCH_UP":result.at(1)=="snapshot"?"SNAPSHOT":count?"DELTA_CHANGED":"DELTA_EMPTY"},body["pollAfterMs"].asInt()/1000.0);
                    PerformanceMetrics::availability("sync",result.at(1),std::chrono::duration<double>(std::chrono::steady_clock::now()-self->started).count(),count);
                    if(result.at(4)=="1")PerformanceMetrics::availability("reset",result.at(6));
                    self->respond(drogon::HttpResponse::newHttpJsonResponse(body));
                });
            });
    }
    void fallback()
    {
        PerformanceMetrics::availability("sync","degraded");
        auto self=shared_from_this();
        drogon::app().getDbClient()->execSqlAsync(R"SQL(
            SELECT inventory.id,inventory.status FROM session_seats inventory
            JOIN seats seat ON seat.id=inventory.seat_id
            JOIN venue_zones zone ON zone.id=seat.zone_id AND zone.venue_id=seat.venue_id
            WHERE inventory.session_id=$1 AND zone.name=$2 ORDER BY zone.sort_order,seat.row_no,seat.seat_no,inventory.id
        )SQL",[self](const drogon::orm::Result &result){
            std::vector<std::array<std::string,2>> rows;
            std::vector<std::string> ids;
            for(const auto &r:result)
            {auto id=r["id"].as<std::string>(); ids.push_back(id); rows.push_back({id,r["status"].as<std::string>()});}
            if(rows.empty())
            {
                SeatRepository{}.sessionExists(self->session,[self](bool exists){self->error(exists?"ZONE_NOT_FOUND":"SESSION_NOT_FOUND");},[self]{self->error("INTERNAL_ERROR");});
                return;
            }
            SeatHoldService{}.readOwners(self->session,ids,[self,rows=std::move(rows)](SeatHoldReadResult holds) mutable{
                self->fallbackSummary(std::move(rows),std::move(holds));
            });
        },[self](const drogon::orm::DrogonDbException &){self->error("INTERNAL_ERROR");},session,zone);
    }
    void fallbackSummary(std::vector<std::array<std::string,2>> rows,SeatHoldReadResult holds)
    {
        auto self=shared_from_this();
        drogon::app().getDbClient()->execSqlAsync(R"SQL(
            SELECT zone.name AS zone,inventory.status,count(*) AS count FROM session_seats inventory
            JOIN seats seat ON seat.id=inventory.seat_id
            JOIN venue_zones zone ON zone.id=seat.zone_id AND zone.venue_id=seat.venue_id WHERE inventory.session_id=$1
            GROUP BY zone.name,zone.sort_order,inventory.status ORDER BY zone.sort_order,inventory.status
        )SQL",[self,rows=std::move(rows),holds=std::move(holds)](const drogon::orm::Result &result) mutable{
            std::vector<std::array<std::string,3>> groups;
            for(const auto &r:result) groups.push_back({r["zone"].as<std::string>(),r["status"].as<std::string>(),r["count"].as<std::string>()});
            self->compute([self,rows=std::move(rows),holds=std::move(holds),groups=std::move(groups)]{
                Json::Value body;
                body["sessionId"]=self->session; body["zone"]=self->zone; body["mode"]="snapshot";
                body["reset"]=true; body["degraded"]=true; body["hasMore"]=false;
                body["pollAfterMs"]=SeatReadConfig::parse(drogon::app().getCustomConfig()["seat_read"]).degradedMs;
                admission::AdmissionMetrics::gauge("ticketing_availability_poll_interval_seconds",{"DEGRADED"},body["pollAfterMs"].asInt()/1000.0);
                body["generation"]=Json::nullValue; body["cursor"]=Json::nullValue;
                body["seats"]=Json::Value(Json::arrayValue); body["zones"]=Json::Value(Json::arrayValue);
                for(std::size_t i=0;i<rows.size();++i)
                {
                    Json::Value seat;seat["id"]=rows[i][0];
                    const auto owner=holds.outcome==SeatHoldOutcome::Applied && holds.owners.size()==rows.size()?holds.owners[i]:std::nullopt;
                    seat["status"]=displaySeatStatus(rows[i][1],owner,self->owner); body["seats"].append(std::move(seat));
                }
                std::vector<std::string> zones;
                Json::Value summaries;
                for(const auto &g:groups)
                {
                    if(!summaries.isMember(g[0]))
                    {
                        zones.push_back(g[0]);auto &z=summaries[g[0]];z["zone"]=g[0];
                        for(const auto *n:{"total","available","held","sold"})z[n]=Json::Int64(0);
                    }
                    auto &z=summaries[g[0]];const auto count=std::stoll(g[2]);
                    const char *field=g[1]=="AVAILABLE"?"available":g[1]=="HELD"?"held":"sold";
                    z[field]=Json::Int64(count); z["total"]=Json::Int64(z["total"].asInt64()+count);
                }
                for(const auto &z:zones)body["zones"].append(summaries[z]);
                self->respond(drogon::HttpResponse::newHttpJsonResponse(body));
            });
        },[self](const drogon::orm::DrogonDbException &){self->error("INTERNAL_ERROR");},session);
    }
};
}

SeatAvailabilityConfig SeatAvailabilityConfig::load()
{
    SeatAvailabilityConfig c;
    const auto &root=drogon::app().getCustomConfig();
    auto integer=[&](const char *section,const char *name,int &target){
        const auto &v=root[section][name];
        if(v.isNull()) return;
        if(!v.isInt64() || v.asInt64()<=0 || v.asInt64()>std::numeric_limits<int>::max()/1000)
            throw std::invalid_argument(std::string(section)+"."+name+" must be a positive bounded integer");
        target=static_cast<int>(v.asInt64());
    };
    integer("seat_availability_read_model","init_lock_seconds",c.initLockSeconds);
    integer("seat_availability_read_model","init_wait_milliseconds",c.initWaitMilliseconds);
    integer("seat_availability_read_model","stream_maxlen",c.streamMaxlen);
    integer("seat_availability_read_model","delta_scan_limit",c.deltaScanLimit);
    integer("seat_availability_read_model","expiry_cleanup_batch",c.expiryCleanupBatch);
    integer("seat_availability_read_model","checkout_owner_cache_ttl_seconds",c.ownerCacheTtlSeconds);
    integer("seat_availability_projection","batch_size",c.projectionBatchSize);
    auto real=[&](const char *name,double &target){
        const auto &v=root["seat_availability_projection"][name];
        if(v.isNull()) return;
        if(!v.isNumeric() || !std::isfinite(v.asDouble()) || v.asDouble()<=0)throw std::invalid_argument(std::string(name)+" must be positive");
        target=v.asDouble();
    };
    real("interval_seconds",c.projectionIntervalSeconds); real("lease_seconds",c.projectionLeaseSeconds);
    return c;
}
void SeatAvailabilityReadModel::configure(std::shared_ptr<SeatMapComputeExecutor> value)
{
    if(executor || !value)throw std::logic_error("availability executor configuration");
    settings=SeatAvailabilityConfig::load(); executor=std::move(value);
}
std::string SeatAvailabilityReadModel::prefix(const std::string &session)
{return "ticketing:seat-availability:{"+session+"}";}
void SeatAvailabilityReadModel::eval(const std::string &script,const std::string &prefix,Strings args,Result result)
{
    args.resize(4);
    auto done=std::make_shared<Result>(std::move(result));
    auto claimed=std::make_shared<std::atomic_bool>(false);
    try
    {
        drogon::app().getRedisClient("seat_holds")->execCommandAsync(
            [done,claimed](const drogon::nosql::RedisResult &result){
                Strings owned;
                try {for(const auto &v:result.asArray())owned.push_back(v.asString());}
                catch(...) {owned={"ERROR"};}
                if(owned.empty())owned={"ERROR"};
                if(!claimed->exchange(true))(*done)(std::move(owned));
            },[done,claimed](const drogon::nosql::RedisException &){if(!claimed->exchange(true))(*done)({"UNAVAILABLE"});},
            "EVAL %b 1 %b %b %b %b %b",script.data(),script.size(),prefix.data(),prefix.size(),
            args[0].data(),args[0].size(),args[1].data(),args[1].size(),args[2].data(),args[2].size(),args[3].data(),args[3].size());
    }
    catch(...) {if(!claimed->exchange(true))(*done)({"UNAVAILABLE"});}
}
void SeatAvailabilityReadModel::read(std::string session,std::string zone,std::string owner,
                                    std::string generation,std::string since,Reply reply)
{
    auto request=std::make_shared<Request>();
    request->session=std::move(session);request->zone=std::move(zone);request->owner=std::move(owner);
    request->generation=std::move(generation);request->since=std::move(since);request->reply=std::move(reply);
    request->token=drogon::utils::getUuid();
    SeatRepository{}.sessionExists(request->session,[request](bool visible){
        if(visible)request->acquire();else request->error("SESSION_NOT_FOUND");
    },[request]{request->error("INTERNAL_ERROR");});
}
void SeatAvailabilityReadModel::apply(std::string session,std::string seat,std::string status,std::string version,Result result)
{
    eval(applyScript,prefix(session),{std::move(seat),std::move(status),std::move(version),std::to_string(settings.streamMaxlen)},std::move(result));
}
std::string SeatAvailabilityReadModel::wrapHold(std::string_view original)
{
    return "local originalKeys=KEYS\nlocal KEYS={string.gsub(string.match(KEYS[1], '^(.*}):'), 'seat%-hold:', 'seat-availability:', 1)}\n"+
        std::string(availability_scripts::common)+"\nlocal streamMaxlen="+std::to_string(SeatAvailabilityConfig::load().streamMaxlen)+
        "\nlocal function originalOperation()\nlocal KEYS=originalKeys\n"+std::string(original)+"\nend\n"+std::string(availability_scripts::hold);
}
} // namespace ticketing
