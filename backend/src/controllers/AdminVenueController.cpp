#include "admission/TrafficControl.h"
#include "controllers/AdminVenueController.h"
#include "services/AdminVenueService.h"
using namespace ticketing;using namespace ticketing::admin;
void AdminVenueController::collection(const drogon::HttpRequestPtr &req,Reply &&reply) const {
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);

    auto body=req->getJsonObject();bool create=req->method()==drogon::Post;
    dispatch([body,create](const DB &db){if(!create)return AdminVenueRepository::list(db);require(bool(body));return AdminVenueRepository::save(db,"",AdminVenueService::validate(*body));},std::move(reply),create?drogon::k201Created:drogon::k200OK);
}
void AdminVenueController::item(const drogon::HttpRequestPtr &req,Reply &&reply,std::string id) const {
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);

    auto body=req->getJsonObject();bool update=req->method()==drogon::Put;
    dispatch([body,update,id](const DB &db){if(!update)return venue(db,id);require(bool(body));return AdminVenueRepository::save(db,id,AdminVenueService::validate(*body));},std::move(reply));
}
