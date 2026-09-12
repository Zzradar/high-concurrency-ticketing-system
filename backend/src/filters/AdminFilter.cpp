#include "filters/AdminFilter.h"
#include "common/ApiResponse.h"
#include "common/AuthContext.h"

namespace ticketing
{
void AdminFilter::doFilter(const drogon::HttpRequestPtr &request,
                           drogon::FilterCallback &&reject,
                           drogon::FilterChainCallback &&accept)
{
    const auto context = authContext(request);
    if (!context || context->role != "ADMIN")
    {
        reject(makeErrorResponse(drogon::k403Forbidden, "ADMIN_REQUIRED",
                                 "Administrator access required"));
        return;
    }
    accept();
}
}  // namespace ticketing
