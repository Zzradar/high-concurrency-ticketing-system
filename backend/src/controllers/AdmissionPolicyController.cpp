#include "admission/TrafficControl.h"
#include "admission/AdmissionRuntime.h"
#include "controllers/AdmissionPolicyController.h"
#include "common/AuthContext.h"
void AdmissionPolicyController::policy(const drogon::HttpRequestPtr &request,
    ticketing::admin::Reply &&reply, std::string eventId) const {
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Admin,std::move(reply));
    if(!trafficReply)return;
    reply=std::move(*trafficReply);

    const auto input=request->getJsonObject();
    const auto body=input?*input:Json::Value{};
    const auto user=ticketing::authenticatedUserId(request);
    const bool update=request->method()==drogon::Put;
    ticketing::admin::dispatch([eventId,body,user,update](const ticketing::admin::DB &db) {
        return update?ticketing::admission::writePolicy(db,eventId,body,user)
                     :ticketing::admission::readPolicy(db,eventId);
    },[reply=std::move(reply),update](const drogon::HttpResponsePtr &response) {
        if(update && response->statusCode()==drogon::k200OK)ticketing::admission::AdmissionRuntime::invalidate();
        response->addHeader("Cache-Control","private, no-store"); reply(response);
    });
}
