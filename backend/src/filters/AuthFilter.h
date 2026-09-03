#pragma once

#include "services/AuthSessionService.h"

#include <drogon/HttpFilter.h>

namespace ticketing
{
class AuthFilter final : public drogon::HttpFilter<AuthFilter>
{
  public:
    void doFilter(const drogon::HttpRequestPtr &request,
                  drogon::FilterCallback &&reject,
                  drogon::FilterChainCallback &&accept) override;

  private:
    AuthSessionService service_;
};
}  // namespace ticketing
