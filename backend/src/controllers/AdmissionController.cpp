#include "admission/TrafficControl.h"
#include "controllers/AdmissionController.h"
#include "admission/AdmissionService.h"
#include "common/AuthContext.h"
#include "common/ApiResponse.h"
namespace {
void handle(const drogon::HttpRequestPtr &r,ticketing::admin::Reply reply,std::string event,const char *op) {
 std::string generation;
 try {
  if(r->method()==drogon::Get)generation=r->getParameter("queueGeneration");
  else if(!r->body().empty()) {
   const auto json=r->getJsonObject();ticketing::admin::require(bool(json));
   ticketing::admin::fields(*json,{"queueGeneration"});
   if(json->isMember("queueGeneration")){ticketing::admin::require((*json)["queueGeneration"].isString());generation=(*json)["queueGeneration"].asString();}
  }
  ticketing::admin::require(generation.empty()||(generation.size()==32&&generation.find_first_not_of("0123456789abcdef")==std::string::npos));
 }catch(...){reply(ticketing::makeErrorResponse(drogon::k400BadRequest,"INVALID_ARGUMENT","Invalid admission request"));return;}
 ticketing::admission::AdmissionService::request(event,ticketing::authenticatedUserId(r),op,generation,std::move(reply));
}
}
void AdmissionController::status(const drogon::HttpRequestPtr &r,ticketing::admin::Reply &&reply,std::string event)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admission,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);
handle(r,std::move(reply),event,"status");}
void AdmissionController::mutate(const drogon::HttpRequestPtr &r,ticketing::admin::Reply &&reply,std::string event)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admission,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);
handle(r,std::move(reply),event,r->method()==drogon::Delete?"leave":"join");}
void AdmissionController::heartbeat(const drogon::HttpRequestPtr &r,ticketing::admin::Reply &&reply,std::string event)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admission,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);
handle(r,std::move(reply),event,"heartbeat");}
