#include "common/SeatReadConfig.h"
#include "common/HttpCache.h"
#include "admission/TrafficConfig.h"
#include "admission/AdmissionPolicy.h"
#include <iostream>
#include "admission/AdmissionConfig.h"
int main() {
    using namespace ticketing::admission;
    for(auto bad:{Json::Value(true),Json::Value("2000"),Json::Value(2000.0),Json::Value(0),Json::Value(10001)}) {
        Json::Value config;config["policy_refresh_ms"]=bad;
        try{Config::parse(config);return 5;}catch(const std::invalid_argument &){}
    }
    Json::Value traffic;
    for(auto name:resourceNames)traffic["bulkheads"][name]=16;
    for(auto name:{"account_capacity","account_rate","event_capacity","event_rate"})traffic[name]=20;
    if(TrafficConfig::parse(traffic).accountCapacity!=20)return 7;
    for(auto field:{"account_capacity","account_rate","event_capacity","event_rate"})for(auto bad:{Json::Value{},Json::Value(true),Json::Value("20"),Json::Value(20.0),Json::Value(0),Json::Value(1000001)}){
      auto invalid=traffic;invalid[field]=bad;try{TrafficConfig::parse(invalid);return 8;}catch(const std::invalid_argument &){}
    }
    for(auto name:resourceNames)for(auto bad:{Json::Value{},Json::Value(true),Json::Value("16"),Json::Value(16.0),Json::Value(0),Json::Value(257)}){
      auto invalid=traffic;invalid["bulkheads"][name]=bad;try{TrafficConfig::parse(invalid);return 9;}catch(const std::invalid_argument &){}
    }
    for(auto bad:{Json::Value(true),Json::Value("60"),Json::Value(60.0),Json::Value(-1),Json::Value(601)}){
      Json::Value invalid;invalid["layout_max_age_seconds"]=bad;try{ticketing::SeatReadConfig::parse(invalid);return 10;}catch(const std::invalid_argument &){}
    }
    for(auto tag:{"W/\"tag\"","\"tag\""," * ","\"other\", W/\"tag\""," W/\"a,b\", \"tag\""})if(!ticketing::ifNoneMatch(tag,"W/\"tag\""))return 11;
    for(auto tag:{"","tag","\"other\"","\"tag\",","\"tag\" garbage","*, \"tag\"","\"tag\", ","\"unterminated"})if(ticketing::ifNoneMatch(tag,"W/\"tag\""))return 12;
    const std::string modes[]={"OFF","OBSERVE","PAUSED","ENFORCED"};
    const int spaces[]={0,1,2,2};
    for(int i=0;i<4;++i)for(int j=0;j<4;++j)
        if(rotatesGeneration(modes[i],modes[j])!=(spaces[j]!=0 && spaces[i]!=spaces[j]))return 6;
    Json::Value v; v["mode"]="OFF"; v["prequeueSeconds"]=0; v["maxActiveUsers"]=10;
    v["admissionRatePerSecond"]=2; v["leaseSeconds"]=30; v["expectedPolicyVersion"]=0;
    if(parsePolicyInput(v).expectedVersion!=0 || defaultPolicy("e")["mode"]!="OFF" || !defaultPolicy("e")["maxActiveUsers"].isNull()) return 1;
    for(auto field:{"prequeueSeconds","maxActiveUsers","admissionRatePerSecond","leaseSeconds","expectedPolicyVersion"}) {
        for(const auto invalid:{Json::Value{},Json::Value(true),Json::Value("1"),Json::Value(1.0),Json::Value(-1),Json::Value(Json::arrayValue),Json::Value(Json::UInt64(9007199254740992ULL))}) {
            auto bad=v;bad[field]=invalid;
            try {parsePolicyInput(bad); return 2;} catch(const ticketing::admin::Error &) {}
        }
    }
    for(const auto mode:{"off"," ENFORCED","", "UNKNOWN"}) {
        auto bad=v;bad["mode"]=mode;
        try {parsePolicyInput(bad); return 3;} catch(const ticketing::admin::Error &) {}
    }
    if(validSecret("") || validSecret(std::string(64,'a')))return 4;
    std::cout<<"Strict policy input and synthetic OFF tests passed\n";
}
