#pragma once
#include <json/json.h>
#include <stdexcept>
namespace ticketing::admission {
struct Config {
 int policyRefreshMs=2000, policyLimit=10000, schedulerBatch=64, schedulerMs=250;
 int pollMs=2000, heartbeatMs=5000, presenceSeconds=30;
 static Config parse(const Json::Value &v) {
  Config c; if(v.isNull())return c;
  if(!v.isObject())throw std::invalid_argument("admission must be an object");
  struct Field{const char *name;int *value;int min,max;};
  const Field fields[]={{"policy_refresh_ms",&c.policyRefreshMs,100,10000},{"policy_limit",&c.policyLimit,1,100000},
   {"scheduler_batch",&c.schedulerBatch,1,256},{"scheduler_ms",&c.schedulerMs,50,1000},
   {"poll_ms",&c.pollMs,500,30000},{"heartbeat_ms",&c.heartbeatMs,1000,10000},{"presence_seconds",&c.presenceSeconds,10,120}};
  for(const auto &name:v.getMemberNames()) {bool known=false;for(const auto &f:fields)known|=name==f.name;if(!known)throw std::invalid_argument("Unknown admission setting");}
  for(const auto &f:fields)if(v.isMember(f.name)) {
   const auto &n=v[f.name];if((n.type()!=Json::intValue&&n.type()!=Json::uintValue)||!n.isInt()||n.asInt()<f.min||n.asInt()>f.max)throw std::invalid_argument("Invalid admission setting");
   *f.value=n.asInt();
  }
  if(c.heartbeatMs*2>=c.presenceSeconds*1000)throw std::invalid_argument("Admission presence must allow two heartbeats");
  return c;
 }
};
}
