#pragma once
#include "admin/AdminCatalog.h"
namespace ticketing {
class AdminEventRepository {
 public:
 static Json::Value list(const admin::DB &);
 static Json::Value detail(const admin::DB &,const std::string &);
 static Json::Value preview(const admin::DB &,const Json::Value &);
 static Json::Value execute(const admin::DB &,const std::string &action,std::string eventId,const std::string &sessionId,const Json::Value &,const std::string &userId);
};
}
