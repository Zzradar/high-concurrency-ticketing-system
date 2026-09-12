#include "admission/TrafficConfig.h"
#include "admission/AdmissionMetrics.h"
#include "admission/AdmissionRuntime.h"
#include "admission/TrafficControl.h"
#include "admission/AdmissionScripts.h"
#include "common/ApiResponse.h"
#include "security/Crypto.h"
#include <set>
namespace ticketing::admission {
namespace {
Bulkhead bulkhead;
int accountCapacity=20,accountRate=10,eventCapacity=200,eventRate=100;

drogon::HttpResponsePtr failure(const char *code,drogon::HttpStatusCode status,const std::string &scope,int retry) {
 Json::Value body;body["code"]=code;body["message"]=code;body["retryAfterMs"]=retry;
 body[status==drogon::k429TooManyRequests?"scope":"resource"]=scope;
 auto response=drogon::HttpResponse::newHttpJsonResponse(body);response->setStatusCode(status);
 response->addHeader("Retry-After",std::to_string(std::max(1,(retry+999)/1000)));
 response->addHeader("Cache-Control","private, no-store");return response;
}
}
drogon::HttpResponsePtr TrafficControl::overloaded(Resource r){AdmissionMetrics::count("ticketing_overload_rejections_total",{resourceNames[static_cast<size_t>(r)]});return failure("SYSTEM_OVERLOADED",drogon::k503ServiceUnavailable,resourceNames[static_cast<size_t>(r)],1000);}
drogon::HttpResponsePtr TrafficControl::transition(const std::shared_ptr<Work> &work,Resource resource,const std::string &session){
 work->permit.reset();work->permit=acquire(resource);
 if(work->permit)return nullptr;
 if(resource==Resource::InventoryWrite)AdmissionRuntime::pauseSession(session);
 return overloaded(resource);
}
void TrafficControl::sample(){for(size_t i=0;i<resourceNames.size();++i){
 AdmissionMetrics::gauge("ticketing_traffic_inflight",{resourceNames[i]},bulkhead.inflight(static_cast<Resource>(i)));
 AdmissionMetrics::gauge("ticketing_traffic_peak_inflight",{resourceNames[i]},bulkhead.highWater(static_cast<Resource>(i)));
}}
void TrafficControl::configure(){
 const auto config=TrafficConfig::parse(drogon::app().getCustomConfig()["traffic_control"]);
 bulkhead.configure(config.limits);accountCapacity=config.accountCapacity;accountRate=config.accountRate;eventCapacity=config.eventCapacity;eventRate=config.eventRate;
}

std::shared_ptr<Bulkhead::Permit> TrafficControl::acquire(Resource r){return bulkhead.acquire(r);}
std::optional<admin::Reply> TrafficControl::wrap(Resource r,admin::Reply reply){
 auto permit=acquire(r);
 if(!permit){reply(overloaded(r));return std::nullopt;}
 struct State{std::atomic<bool> complete{false};std::shared_ptr<Bulkhead::Permit> permit;admin::Reply reply;};
 AdmissionMetrics::gauge("ticketing_traffic_inflight",{resourceNames[static_cast<size_t>(r)]},bulkhead.inflight(r));
 auto state=std::make_shared<State>();state->permit=std::move(permit);state->reply=std::move(reply);
 return [state,r](const drogon::HttpResponsePtr &response){
  if(state->complete.exchange(true))return;
  state->permit.reset();
  AdmissionMetrics::gauge("ticketing_traffic_inflight",{resourceNames[static_cast<size_t>(r)]},bulkhead.inflight(r));
  if(r!=Resource::PublicStaticRead || response->statusCode()>=400)response->addHeader("Cache-Control","private, no-store");
  auto reply=std::move(state->reply);reply(response);
 };
}
drogon::HttpResponsePtr TrafficControl::rate(const RuntimePolicy &p,const std::string &user,const std::string &op){
 if(p.mode=="OFF")return nullptr;
 static const std::set<std::string> operations={"ADMISSION_JOIN","ADMISSION_STATUS","ADMISSION_HEARTBEAT","AVAILABILITY_SYNC","CHECKOUT_CREATE","SEAT_REPLACE","CONFIRM","RESERVATION_CREATE"};
 if(!operations.count(op))throw std::invalid_argument("Unknown admission operation");
 const auto root="ticketing:admission:{evt:"+RedisAdmissionStore::eventHash(p.eventId)+"}:"+p.generation+":rate:"+op+":";
 const auto account=root+sha256Hex(user),event=root+"event";
 try {
  const auto result=drogon::app().getRedisClient("traffic_control")->execCommandSync<RedisAdmissionStore::Result>(
   [](const drogon::nosql::RedisResult &r){RedisAdmissionStore::Result out;for(const auto &x:r.asArray())out.push_back(x.asString());return out;},
   "EVAL %b 2 %s %s %d %d %d %d 1",scripts::token_bucket.data(),scripts::token_bucket.size(),account.c_str(),event.c_str(),accountCapacity,accountRate,eventCapacity,eventRate);
  if(result.size()>=3 && result[0]=="RATE_LIMITED")AdmissionMetrics::count("ticketing_rate_limit_rejections_total",{p.mode,result[1],op});
  if(p.mode=="OBSERVE")return nullptr;
  if(result.size()>=3 && result[0]=="RATE_LIMITED")return failure("RATE_LIMITED",drogon::k429TooManyRequests,result[1],std::stoi(result[2]));
  if(result.empty()||result[0]!="ALLOWED")return failure("ADMISSION_UNAVAILABLE",drogon::k503ServiceUnavailable,"REDIS",1000);
  return nullptr;
 }catch(...){return p.mode=="OBSERVE"?nullptr:failure("ADMISSION_UNAVAILABLE",drogon::k503ServiceUnavailable,"REDIS",1000);}
}
}
