#pragma once
#include "services/AdminEventService.h"
class AdminEventController : public drogon::HttpController<AdminEventController> {
 public:
 METHOD_LIST_BEGIN
 ADD_METHOD_TO(AdminEventController::collection,"/admin/events",drogon::Get,drogon::Post,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::item,"/admin/events/{eventId}",drogon::Get,drogon::Put,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::display,"/admin/events/{eventId}/display",drogon::Patch,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::sessions,"/admin/events/{eventId}/sessions",drogon::Post,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::session,"/admin/events/{eventId}/sessions/{sessionId}",drogon::Put,drogon::Delete,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::prices,"/admin/events/{eventId}/sessions/{sessionId}/prices",drogon::Put,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::preview,"/admin/events/{eventId}/publish-preview",drogon::Get,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminEventController::publish,"/admin/events/{eventId}/publish",drogon::Post,"ticketing::AuthFilter","ticketing::AdminFilter");
 METHOD_LIST_END
 void collection(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&) const;
 void item(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void display(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void sessions(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void session(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string,std::string) const;
 void prices(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string,std::string) const;
 void preview(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void publish(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
};
