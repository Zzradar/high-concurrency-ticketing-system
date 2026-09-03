#include "filters/AuthFilter.h"

#include "common/ApiResponse.h"
#include "common/AuthContext.h"
#include "security/AuthConfig.h"
#include "security/AuthHttp.h"

#include <memory>
#include <utility>

namespace ticketing
{
void AuthFilter::doFilter(const drogon::HttpRequestPtr &request,
                          drogon::FilterCallback &&reject,
                          drogon::FilterChainCallback &&accept)
{
    auto rejectPtr = std::make_shared<drogon::FilterCallback>(std::move(reject));
    auto acceptPtr =
        std::make_shared<drogon::FilterChainCallback>(std::move(accept));
    const auto rawToken =
        request->getCookie(AuthConfig::load().cookieName);
    service_.authenticate(
        rawToken,
        [request, rejectPtr, acceptPtr](AuthenticateResult result) {
            if (result.outcome == AuthenticateOutcome::Unavailable)
            {
                (*rejectPtr)(makeErrorResponse(drogon::k503ServiceUnavailable,
                                               "AUTH_UNAVAILABLE",
                                               "Authentication service unavailable"));
                return;
            }
            if (result.outcome != AuthenticateOutcome::Authenticated ||
                !result.session)
            {
                (*rejectPtr)(makeErrorResponse(drogon::k401Unauthorized,
                                               "UNAUTHENTICATED",
                                               "Authentication required"));
                return;
            }
            const auto method = request->method();
            const bool unsafe = method == drogon::Post || method == drogon::Put ||
                                method == drogon::Patch || method == drogon::Delete;
            if (unsafe && !validCsrf(request))
            {
                (*rejectPtr)(makeErrorResponse(drogon::k403Forbidden,
                                               "CSRF_INVALID",
                                               "CSRF validation failed"));
                return;
            }
            request->attributes()->insert(
                kAuthAttribute,
                AuthContext{.userId = result.session->userId,
                            .sessionId = result.session->sessionId,
                            .tokenHash = std::move(result.tokenHash),
                            .username = result.session->username,
                            .displayName = result.session->displayName});
            (*acceptPtr)();
        });
}
}  // namespace ticketing
