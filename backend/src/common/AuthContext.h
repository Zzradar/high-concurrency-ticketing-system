#pragma once

#include <drogon/HttpRequest.h>

#include <optional>
#include <string>

namespace ticketing
{
inline constexpr const char *kAuthAttribute = "ticketing.auth";

struct AuthContext
{
    std::string userId;
    std::string sessionId;
    std::string tokenHash;
    std::string username;
    std::string displayName;
};

inline std::optional<AuthContext> authContext(
    const drogon::HttpRequestPtr &request)
{
    try
    {
        return request->attributes()->get<AuthContext>(kAuthAttribute);
    }
    catch (...)
    {
        return std::nullopt;
    }
}

inline std::string authenticatedUserId(
    const drogon::HttpRequestPtr &request)
{
    const auto context = authContext(request);
    return context ? context->userId : std::string{};
}
}  // namespace ticketing
