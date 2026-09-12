#include "admission/TrafficControl.h"
#include "controllers/AdminEventController.h"
#include "common/AuthContext.h"
using namespace ticketing;using namespace ticketing::admin;
namespace {
void handle(const drogon::HttpRequestPtr &req,Reply reply,std::string action,std::string eid="",std::string sid="") {
    auto body=req->getJsonObject();AdminEventService::handle(action,eid,sid,body?*body:Json::Value{},authenticatedUserId(req),std::move(reply));
}
}
void AdminEventController::collection(const drogon::HttpRequestPtr &r,Reply &&c)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),r->method()==drogon::Post?"create":"list");}
void AdminEventController::item(const drogon::HttpRequestPtr &r,Reply &&c,std::string e)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),r->method()==drogon::Put?"update":"detail",e);}
void AdminEventController::display(const drogon::HttpRequestPtr &r,Reply &&c,std::string e)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),"display",e);}
void AdminEventController::sessions(const drogon::HttpRequestPtr &r,Reply &&c,std::string e)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),"session-create",e);}
void AdminEventController::session(const drogon::HttpRequestPtr &r,Reply &&c,std::string e,std::string s)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),r->method()==drogon::Delete?"session-delete":"session-update",e,s);}
void AdminEventController::prices(const drogon::HttpRequestPtr &r,Reply &&c,std::string e,std::string s)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),"prices",e,s);}
void AdminEventController::preview(const drogon::HttpRequestPtr &r,Reply &&c,std::string e)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),"preview",e);}
void AdminEventController::publish(const drogon::HttpRequestPtr &r,Reply &&c,std::string e)const{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(c));
    if(!trafficReply)return;
    c=std::move(*trafficReply);
handle(r,std::move(c),"publish",e);}
