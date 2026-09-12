#pragma once
#include "admin/AdminCatalog.h"
class AdmissionController : public drogon::HttpController<AdmissionController> {
public:
 METHOD_LIST_BEGIN
 ADD_METHOD_TO(AdmissionController::status,"/events/{eventId}/admission",drogon::Get,"ticketing::AdmissionReadFilter");
 ADD_METHOD_TO(AdmissionController::mutate,"/events/{eventId}/admission",drogon::Post,drogon::Delete,"ticketing::AuthFilter");
 ADD_METHOD_TO(AdmissionController::heartbeat,"/events/{eventId}/admission/heartbeat",drogon::Post,"ticketing::AdmissionReadFilter");
 METHOD_LIST_END
 void status(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void mutate(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
 void heartbeat(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
};
