#pragma once
#include "admission/AdmissionRuntime.h"
#include <ctime>
#include <iomanip>
#include <sstream>
namespace ticketing::admission {
// Read-only presentation projection. It cannot authorize inventory or create a queue position.
inline Json::Value withPublicAdmission(Json::Value body,const std::string &eventId) {
 Json::Value summary;
 summary["required"]=true;summary["state"]="UNAVAILABLE";summary["prequeueStartsAt"]=Json::nullValue;
 if(AdmissionRuntime::ready()) {
  const auto policy=AdmissionRuntime::policy(eventId);
  if(policy) {
   const auto &p=*policy;
   if(p.mode=="OFF"||p.mode=="OBSERVE") {summary["required"]=false;summary["state"]="NOT_REQUIRED";}
   else {
    const auto now=trantor::Date::now().microSecondsSinceEpoch()/1000;
    summary["state"]=now>=p.endsMs?"SALES_ENDED":p.mode=="PAUSED"?"PAUSED":now<p.startsMs?"PREQUEUE":"OPEN";
    const auto milliseconds=p.startsMs-p.prequeueSeconds*1000LL;
    const std::time_t seconds=milliseconds/1000;std::tm tm{};
#ifdef _WIN32
    gmtime_s(&tm,&seconds);
#else
    gmtime_r(&seconds,&tm);
#endif
    std::ostringstream formatted;formatted<<std::put_time(&tm,"%Y-%m-%dT%H:%M:%S")<<'.'<<std::setw(3)<<std::setfill('0')<<(milliseconds%1000)<<'Z';
    summary["prequeueStartsAt"]=formatted.str();
   }
  }
 }
 body["admission"]=std::move(summary);return body;
}
}
