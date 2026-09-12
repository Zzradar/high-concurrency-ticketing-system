#pragma once
#include "admin/AdminCatalog.h"
class AdminVenueController : public drogon::HttpController<AdminVenueController> {
 public:
 METHOD_LIST_BEGIN
 ADD_METHOD_TO(AdminVenueController::collection,"/admin/venues",drogon::Get,drogon::Post,"ticketing::AuthFilter","ticketing::AdminFilter");
 ADD_METHOD_TO(AdminVenueController::item,"/admin/venues/{venueId}",drogon::Get,drogon::Put,"ticketing::AuthFilter","ticketing::AdminFilter");
 METHOD_LIST_END
 void collection(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&) const;
 void item(const drogon::HttpRequestPtr &,ticketing::admin::Reply &&,std::string) const;
};
