#pragma once
#include "admission/Bulkhead.h"
#include "admission/RedisAdmissionStore.h"
#include "admin/AdminCatalog.h"
#include <optional>
namespace ticketing::admission {
class TrafficControl {
public:
 static void configure();
 static void sample();
 struct Work { std::shared_ptr<Bulkhead::Permit> permit; std::atomic<bool> completed{false}; };
 template<class Result> static std::function<void(Result)> bind(std::shared_ptr<Work> work,std::function<void(Result)> reply){
  return [work,reply=std::move(reply)](Result result){if(work->completed.exchange(true))return;work->permit.reset();reply(std::move(result));};
 }
 static drogon::HttpResponsePtr transition(const std::shared_ptr<Work> &,Resource,const std::string &session={});
 static drogon::HttpResponsePtr overloaded(Resource);
 static std::optional<admin::Reply> wrap(Resource resource,admin::Reply reply);
 static std::shared_ptr<Bulkhead::Permit> acquire(Resource resource);
 static drogon::HttpResponsePtr rate(const RuntimePolicy &,const std::string &user,const std::string &operation);
};
}
