#pragma once
#include <drogon/HttpFilter.h>
namespace ticketing
{
// Routes must run AuthFilter before AdminFilter.
class AdminFilter final : public drogon::HttpFilter<AdminFilter>
{
  public:
    void doFilter(const drogon::HttpRequestPtr &request,
                  drogon::FilterCallback &&reject,
                  drogon::FilterChainCallback &&accept) override;
};
}  // namespace ticketing
