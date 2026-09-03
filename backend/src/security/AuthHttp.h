#pragma once

#include "repositories/UserSessionRepository.h"

#include <drogon/HttpRequest.h>
#include <drogon/HttpResponse.h>

#include <string>

namespace ticketing
{
bool allowedOrigin(const drogon::HttpRequestPtr &request);
bool validCsrf(const drogon::HttpRequestPtr &request);
void addLoginCookies(drogon::HttpResponsePtr &response,
                     const std::string &rawToken,
                     const std::string &csrfToken,
                     const AuthSessionRecord &session);
void clearAuthCookies(drogon::HttpResponsePtr &response);
}  // namespace ticketing
