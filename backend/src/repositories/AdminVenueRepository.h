#pragma once
#include "admin/AdminCatalog.h"
namespace ticketing {
class AdminVenueRepository {
 public:
 static Json::Value list(const admin::DB &);
 static Json::Value save(const admin::DB &,std::string,const Json::Value &);
};
}
