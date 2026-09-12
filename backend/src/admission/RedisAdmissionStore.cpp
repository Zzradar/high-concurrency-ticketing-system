#include "admission/AdmissionMetrics.h"
#include "admission/RedisAdmissionStore.h"
#include "admission/AdmissionPolicy.h"
#include "admission/AdmissionConfig.h"
#include "admission/AdmissionScripts.h"
#include "security/Crypto.h"
#include <cstdlib>
namespace ticketing::admission {
std::string RedisAdmissionStore::eventHash(const std::string &eventId){return sha256Hex(eventId);}
std::array<std::string,9> RedisAdmissionStore::keys(const RuntimePolicy &p) {
 const auto root="ticketing:admission:{evt:"+eventHash(p.eventId)+"}:";
 const auto g=root+p.generation+":";
 return {root+"runtime",g+"prequeue",g+"waiting",g+"presence",g+"active",g+"heartbeat",g+"sequence",g+"release",g+"pause"};
}
RedisAdmissionStore::Result RedisAdmissionStore::run(const RuntimePolicy &p,const std::string &op,const std::string &user,bool bootstrap) {
 const auto config=Config::parse(drogon::app().getCustomConfig()["admission"]);
 if(p.mode=="OFF")return {"NOT_REQUIRED"};
 if(!secretAvailable())return {"UNAVAILABLE"};
 const auto identity=sha256Hex(user);
 // Fixed-length hexadecimal pieces make the ranking identity unambiguous.
 const auto rank=hmacSha256Hex(std::getenv("TICKETING_ADMISSION_HMAC_SECRET"),eventHash(p.eventId)+p.generation+identity);
 const auto score=std::stoull(rank.substr(0,13),nullptr,16);
 std::array<std::string,25> values;const auto names=keys(p);
 for(size_t i=0;i<9;++i)values[i]=names[i];
 const std::array<std::string,16> args={op,p.generation,std::to_string(p.version),p.mode,
  std::to_string(p.startsMs-p.prequeueSeconds*1000LL),std::to_string(p.startsMs),std::to_string(p.endsMs),
  std::to_string(p.capacity),std::to_string(p.rate),std::to_string(p.leaseSeconds*1000),
  std::to_string(config.presenceSeconds*1000),std::to_string(config.heartbeatMs),identity,
  std::to_string(score),std::to_string(config.schedulerBatch),bootstrap?"1":"0"};
 for(size_t i=0;i<16;++i)values[i+9]=args[i];
 try {
  auto result=drogon::app().getRedisClient("traffic_control")->execCommandSync<Result>(
   [](const drogon::nosql::RedisResult &result){Result owned;for(const auto &v:result.asArray())owned.push_back(v.asString());return owned;},
   "EVAL %b 9 %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s",scripts::waiting_room.data(),scripts::waiting_room.size(),
   values[0].c_str(),
   values[1].c_str(),
   values[2].c_str(),
   values[3].c_str(),
   values[4].c_str(),
   values[5].c_str(),
   values[6].c_str(),
   values[7].c_str(),
   values[8].c_str(),
   values[9].c_str(),
   values[10].c_str(),
   values[11].c_str(),
   values[12].c_str(),
   values[13].c_str(),
   values[14].c_str(),
   values[15].c_str(),
   values[16].c_str(),
   values[17].c_str(),
   values[18].c_str(),
   values[19].c_str(),
   values[20].c_str(),
   values[21].c_str(),
   values[22].c_str(),
   values[23].c_str(),
   values[24].c_str());
  if(op!="sync" && op!="tick" && !result.empty())AdmissionMetrics::count("ticketing_admission_decisions_total",{p.mode,result[0],op=="join"?"ADMISSION_JOIN":op=="heartbeat"?"ADMISSION_HEARTBEAT":op=="leave"?"ADMISSION_LEAVE":"ADMISSION_STATUS"});
  return result;
 }catch(...){return {"UNAVAILABLE"};}
}
}
