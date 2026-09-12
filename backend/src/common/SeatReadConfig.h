#pragma once
#include <json/json.h>
#include <stdexcept>
namespace ticketing {
struct SeatReadConfig {
 int maxAge=60,staleWhileRevalidate=15,snapshotMs=2000,changedMs=2000,emptyMs=5000,degradedMs=10000;
 static SeatReadConfig parse(const Json::Value &value){
  SeatReadConfig c;if(value.isNull())return c;if(!value.isObject())throw std::invalid_argument("seat_read must be an object");
  struct Field{const char *name;int *out;int low,high;};
  const Field fields[]={{"layout_max_age_seconds",&c.maxAge,0,600},{"layout_stale_seconds",&c.staleWhileRevalidate,0,60},{"snapshot_poll_ms",&c.snapshotMs,500,30000},{"changed_poll_ms",&c.changedMs,500,30000},{"empty_poll_ms",&c.emptyMs,500,30000},{"degraded_poll_ms",&c.degradedMs,500,30000}};
  for(const auto &key:value.getMemberNames()){bool found=false;for(const auto &f:fields)found|=key==f.name;if(!found)throw std::invalid_argument("Unknown seat_read setting");}
  for(const auto &f:fields)if(value.isMember(f.name)){
   const auto &v=value[f.name];if((v.type()!=Json::intValue&&v.type()!=Json::uintValue)||!v.isInt()||v.asInt()<f.low||v.asInt()>f.high)throw std::invalid_argument("Invalid seat_read integer");*f.out=v.asInt();
  }
  if(c.changedMs>c.emptyMs||c.emptyMs>c.degradedMs)throw std::invalid_argument("Invalid seat_read polling order");
  return c;
 }
};
}
