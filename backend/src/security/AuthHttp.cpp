#include "security/AuthHttp.h"

#include "security/AuthConfig.h"
#include "security/Crypto.h"

#include <algorithm>
#include <chrono>
#include <limits>

namespace
{
drogon::Cookie authCookie(const std::string &name,
                          const std::string &value,
                          bool httpOnly,
                          int maxAge)
{
    const auto config = ticketing::AuthConfig::load();
    drogon::Cookie cookie{name, value};
    cookie.setHttpOnly(httpOnly);
    cookie.setSecure(config.cookieSecure);
    cookie.setPath("/");
    cookie.setSameSite(drogon::Cookie::SameSite::kLax);
    cookie.setMaxAge(maxAge);
    return cookie;
}
}  // namespace

namespace ticketing
{
bool allowedOrigin(const drogon::HttpRequestPtr &request)
{
    const auto origin = request->getHeader("Origin");
    const auto config = AuthConfig::load();
    return std::find(config.allowedOrigins.begin(), config.allowedOrigins.end(),
                     origin) != config.allowedOrigins.end();
}

bool validCsrf(const drogon::HttpRequestPtr &request)
{
    if (!allowedOrigin(request)) return false;
    const auto config = AuthConfig::load();
    const auto cookie = request->getCookie(config.csrfCookieName);
    const auto header = request->getHeader("X-CSRF-Token");
    return !cookie.empty() && !header.empty() && constantTimeEqual(cookie, header);
}

void addLoginCookies(drogon::HttpResponsePtr &response,
                     const std::string &rawToken,
                     const std::string &csrfToken,
                     const AuthSessionRecord &session)
{
    const auto config = AuthConfig::load();
    const auto now = std::chrono::duration_cast<std::chrono::seconds>(
                         std::chrono::system_clock::now().time_since_epoch())
                         .count();
    const auto remaining = std::max<std::int64_t>(
        0, std::min(config.absoluteTimeoutSeconds,
                    session.absoluteExpiresAtEpoch - now));
    const auto maxAge = static_cast<int>(std::min<std::int64_t>(
        remaining, std::numeric_limits<int>::max()));
    response->addCookie(authCookie(config.cookieName, rawToken, true, maxAge));
    response->addCookie(
        authCookie(config.csrfCookieName, csrfToken, false, maxAge));
}

void clearAuthCookies(drogon::HttpResponsePtr &response)
{
    const auto config = AuthConfig::load();
    response->addCookie(authCookie(config.cookieName, "", true, 0));
    response->addCookie(authCookie(config.csrfCookieName, "", false, 0));
}
}  // namespace ticketing
