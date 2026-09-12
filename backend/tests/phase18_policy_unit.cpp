#include "admission/AdmissionPolicy.h"
#include <iostream>
#include "admission/AdmissionConfig.h"
int main() {
    using namespace ticketing::admission;
    for(auto bad:{Json::Value(true),Json::Value("2000"),Json::Value(2000.0),Json::Value(0),Json::Value(10001)}) {
        Json::Value config;config["policy_refresh_ms"]=bad;
        try{Config::parse(config);return 5;}catch(const std::invalid_argument &){}
    }
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
