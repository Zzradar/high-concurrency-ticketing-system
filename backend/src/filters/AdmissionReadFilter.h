#pragma once
#include <drogon/HttpFilter.h>
#include "services/AuthSessionService.h"
namespace ticketing {
class AdmissionReadFilter : public drogon::HttpFilter<AdmissionReadFilter> {
public:
 void doFilter(const drogon::HttpRequestPtr &,drogon::FilterCallback &&,drogon::FilterChainCallback &&) override;
private: AuthSessionService service_;
};
}
