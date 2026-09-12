#include "admission/AdmissionService.h"
#include "admission/AdmissionRuntime.h"
#include "admission/AdmissionConfig.h"
#include "services/SeatMapComputeExecutor.h"
#include "common/ApiResponse.h"
#include <atomic>
#include <ctime>
#include <iomanip>
#include <sstream>
namespace ticketing::admission {
namespace {
SeatMapComputeExecutor workers(4,4);
std::atomic<unsigned> inflight{0};
std::string iso(int64_t ms) {
 const std::time_t seconds=ms/1000;std::tm tm{};
#ifdef _WIN32
 gmtime_s(&tm,&seconds);
#else
 gmtime_r(&seconds,&tm);
#endif
 std::ostringstream out;out<<std::put_time(&tm,"%Y-%m-%dT%H:%M:%S")<<'.'<<std::setw(3)<<std::setfill('0')<<(ms%1000)<<'Z';return out.str();
}
drogon::HttpResponsePtr error(const char *code,drogon::HttpStatusCode status=drogon::k503ServiceUnavailable) {
 auto r=makeErrorResponse(status,code,code);r->addHeader("Cache-Control","private, no-store");
 if(status==drogon::k503ServiceUnavailable)r->addHeader("Retry-After","1");
 return r;
}
void submit(std::function<void(admin::Reply)> task,admin::Reply completion) {
 auto done=std::make_shared<admin::Reply>(std::move(completion));
 unsigned current=inflight.load();
 do {if(current>=4){(*done)(error("SYSTEM_OVERLOADED"));return;}}while(!inflight.compare_exchange_weak(current,current+1));
 auto claimed=std::make_shared<std::atomic<bool>>(false);
 auto finish=[claimed,done](const drogon::HttpResponsePtr &response){if(!claimed->exchange(true)){--inflight;(*done)(response);}};
 auto failure=[finish]{finish(error("ADMISSION_UNAVAILABLE"));};
 if(!workers.trySubmit([task,finish]{task(finish);},failure))failure();
}
drogon::HttpResponsePtr response(const RuntimePolicy &p,const RedisAdmissionStore::Result &r) {
 const auto config=Config::parse(drogon::app().getCustomConfig()["admission"]);
 const auto state=r.at(0);
 const int64_t now=r.size()>1?std::stoll(r[1]):trantor::Date::now().microSecondsSinceEpoch()/1000;
 Json::Value body;body["state"]=state;body["queueGeneration"]=p.mode=="OFF"||p.mode=="OBSERVE"?Json::Value{}:Json::Value(p.generation);
 body["positionApprox"]=r.size()>3 && std::stoll(r[3])>0?Json::Value(Json::Int64(std::stoll(r[3]))):Json::Value{};
 body["admittedUntil"]=state=="ADMITTED"&&r.size()>2?Json::Value(iso(std::stoll(r[2]))):Json::Value{};
 body["pollAfterMs"]=config.pollMs;
 body["heartbeatAfterMs"]=state=="ADMITTED"||state=="WAITING"||state=="PREQUEUED"||state=="PAUSED"?Json::Value(config.heartbeatMs):Json::Value{};
 body["serverTime"]=iso(now);
 body["joinAllowed"]=p.mode!="OFF"&&p.mode!="OBSERVE"&&now>=p.startsMs-p.prequeueSeconds*1000LL&&now<p.endsMs;
 auto result=drogon::HttpResponse::newHttpJsonResponse(body);result->addHeader("Cache-Control","private, no-store");return result;
}
}
void AdmissionService::request(std::string event,std::string user,std::string op,std::string expected,admin::Reply reply) {
 submit([event,user,op,expected](admin::Reply done){
  if(!AdmissionRuntime::ready()){done(error("ADMISSION_UNAVAILABLE"));return;}
  const auto found=AdmissionRuntime::policy(event);
  if(!found || !found->published){done(error("EVENT_NOT_FOUND",drogon::k404NotFound));return;}
  const auto &p=*found;
  if(p.mode=="OFF" || p.mode=="OBSERVE") {
   if(p.mode=="OBSERVE" && op=="join")RedisAdmissionStore::run(p,op,user);
   done(response(p,{"NOT_REQUIRED"}));return;
  }
  const auto now=trantor::Date::now().microSecondsSinceEpoch()/1000;
  if(now>=p.endsMs){done(response(p,{"SALES_ENDED"}));return;}
  if(!expected.empty()&&expected!=p.generation){done(response(p,{"RESET_REQUIRED"}));return;}
  if(!p.redisReady){done(error("ADMISSION_UNAVAILABLE"));return;}
  const auto result=RedisAdmissionStore::run(p,op,user);
  if(result.empty()||result[0]=="UNAVAILABLE"||result[0]=="INVALID"||result[0]=="SEQUENCE_EXHAUSTED")done(error("ADMISSION_UNAVAILABLE"));
  else if(result[0]=="ADMISSION_NOT_OPEN")done(error("ADMISSION_NOT_OPEN",drogon::k409Conflict));
  else done(response(p,result));
 },std::move(reply));
}
void AdmissionService::guard(std::string session,std::string user,admin::Reply completion) {
 if(AdmissionRuntime::ready()) {
  const auto event=AdmissionRuntime::eventForSession(session);
  const auto policy=event?AdmissionRuntime::policy(*event):std::nullopt;
  if(policy && policy->mode=="OFF"){completion(nullptr);return;}
 }
 submit([session,user](admin::Reply done){
  if(!AdmissionRuntime::ready()){done(error("ADMISSION_UNAVAILABLE"));return;}
  const auto event=AdmissionRuntime::eventForSession(session);
  // Missing sessions remain subject to the original PostgreSQL not-found/DRAFT check.
  if(!event){
   const auto rows=drogon::app().getDbClient()->execSqlSync("SELECT event_id FROM sessions WHERE id=$1",session);
   if(rows.empty()){done(nullptr);return;}
   const auto eventPolicy=AdmissionRuntime::policy(rows[0]["event_id"].as<std::string>());
   if(eventPolicy && eventPolicy->mode!="OFF"){done(error("ADMISSION_UNAVAILABLE"));return;}
   done(nullptr);return;
  }
  const auto p=AdmissionRuntime::policy(*event);
  if(!p || p->mode=="OFF"){done(nullptr);return;}
  if(!p->published){done(error("SESSION_NOT_FOUND",drogon::k404NotFound));return;}
  if(p->mode=="OBSERVE") {if(!user.empty()){RedisAdmissionStore::run(*p,"join",user);RedisAdmissionStore::run(*p,"status",user);}done(nullptr);return;}
  if(user.empty()){done(error("UNAUTHENTICATED",drogon::k401Unauthorized));return;}
  if(!p->redisReady){done(error("ADMISSION_UNAVAILABLE"));return;}
  const auto result=RedisAdmissionStore::run(*p,"status",user);
  if(result.empty() || result[0]=="UNAVAILABLE"||result[0]=="RESET_REQUIRED")done(error("ADMISSION_UNAVAILABLE"));
  else if(result[0]!="ADMITTED")done(error("ADMISSION_REQUIRED",drogon::k409Conflict));
  else done(nullptr);
 },std::move(completion));
}
void AdmissionService::stop(){workers.shutdown();}
}
