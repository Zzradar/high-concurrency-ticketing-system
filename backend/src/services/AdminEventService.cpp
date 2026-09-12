#include "services/AdminEventService.h"
namespace ticketing {
void AdminEventService::handle(std::string action,std::string eventId,std::string sessionId,Json::Value body,std::string user,admin::Reply reply) {
    auto status=action=="create"||action=="session-create"?drogon::k201Created:drogon::k200OK;
    admin::dispatch([action,eventId,sessionId,body,user](const admin::DB &db){return AdminEventRepository::execute(db,action,eventId,sessionId,body,user);},std::move(reply),status);
}
}
