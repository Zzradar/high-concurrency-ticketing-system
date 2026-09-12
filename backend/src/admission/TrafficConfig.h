#pragma once
#include "admission/Bulkhead.h"
#include <json/json.h>
#include <set>
namespace ticketing::admission {
struct TrafficConfig {
 std::array<unsigned,8> limits{16,16,16,16,16,16,16,2};
 unsigned accountCapacity=20,accountRate=10,eventCapacity=200,eventRate=100;
 static unsigned number(const Json::Value &v,unsigned high){
  if((v.type()!=Json::intValue&&v.type()!=Json::uintValue)||!v.isUInt()||v.asUInt()<1||v.asUInt()>high)throw std::invalid_argument("Invalid traffic_control integer");
  return v.asUInt();
 }
 static TrafficConfig parse(const Json::Value &v){
  TrafficConfig c;if(v.isNull())return c;
  if(!v.isObject())throw std::invalid_argument("traffic_control must be an object");
  const std::set<std::string> allowed={"bulkheads","account_capacity","account_rate","event_capacity","event_rate"};
  if(v.size()!=allowed.size())throw std::invalid_argument("Incomplete traffic_control setting");
  for(const auto &key:v.getMemberNames())if(!allowed.count(key))throw std::invalid_argument("Unknown traffic_control setting");
  const auto &heads=v["bulkheads"];if(!heads.isObject()||heads.size()!=c.limits.size())throw std::invalid_argument("Invalid bulkheads");
  for(size_t i=0;i<c.limits.size();++i)c.limits[i]=number(heads[resourceNames[i]],256);
  c.accountCapacity=number(v["account_capacity"],1000000);c.accountRate=number(v["account_rate"],1000000);
  c.eventCapacity=number(v["event_capacity"],1000000);c.eventRate=number(v["event_rate"],1000000);return c;
 }
};
}
