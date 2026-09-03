#include "controllers/AuthController.h"

#include "common/ApiResponse.h"
#include "common/AuthContext.h"
#include "security/AuthHttp.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;

Json::Value userJson(const ticketing::AuthSessionRecord &session)
{
    Json::Value user;
    user["id"] = session.userId;
    user["username"] = session.username;
    user["displayName"] = session.displayName;
    return user;
}
}  // namespace

void AuthController::login(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto done = std::make_shared<HttpCallback>(std::move(callback));
    if (!ticketing::allowedOrigin(request))
    {
        (*done)(ticketing::makeErrorResponse(drogon::k403Forbidden,
                                             "CSRF_INVALID",
                                             "Origin is not allowed"));
        return;
    }
    const auto body = request->getJsonObject();
    if (!body || !(*body)["username"].isString() ||
        !(*body)["password"].isString())
    {
        (*done)(ticketing::makeErrorResponse(drogon::k400BadRequest,
                                             "INVALID_ARGUMENT",
                                             "Invalid login request"));
        return;
    }
    service_.login(
        (*body)["username"].asString(), (*body)["password"].asString(),
        request->peerAddr().toIp(),
        [done](ticketing::LoginResult result) mutable {
            using ticketing::LoginOutcome;
            if (result.outcome == LoginOutcome::Succeeded && result.session)
            {
                auto response = drogon::HttpResponse::newHttpJsonResponse(
                    userJson(*result.session));
                ticketing::addLoginCookies(response, result.rawToken,
                                           result.csrfToken, *result.session);
                (*done)(response);
                return;
            }
            if (result.outcome == LoginOutcome::InvalidArgument)
            {
                (*done)(ticketing::makeErrorResponse(drogon::k400BadRequest,
                                                     "INVALID_ARGUMENT",
                                                     "Invalid login request"));
                return;
            }
            if (result.outcome == LoginOutcome::InvalidCredentials)
            {
                (*done)(ticketing::makeErrorResponse(drogon::k401Unauthorized,
                                                     "INVALID_CREDENTIALS",
                                                     "Invalid username or password"));
                return;
            }
            if (result.outcome == LoginOutcome::TooManyAttempts)
            {
                (*done)(ticketing::makeErrorResponse(
                    drogon::k429TooManyRequests, "TOO_MANY_LOGIN_ATTEMPTS",
                    "Too many login attempts"));
                return;
            }
            (*done)(ticketing::makeErrorResponse(
                drogon::k503ServiceUnavailable,
                result.outcome == LoginOutcome::Busy ? "AUTH_BUSY"
                                                     : "AUTH_UNAVAILABLE",
                "Authentication service unavailable"));
        });
}

void AuthController::me(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    const auto auth = ticketing::authContext(request);
    if (!auth)
    {
        callback(ticketing::makeErrorResponse(drogon::k401Unauthorized,
                                              "UNAUTHENTICATED",
                                              "Authentication required"));
        return;
    }
    Json::Value user;
    user["id"] = auth->userId;
    user["username"] = auth->username;
    user["displayName"] = auth->displayName;
    callback(drogon::HttpResponse::newHttpJsonResponse(user));
}

void AuthController::logout(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    const auto auth = ticketing::authContext(request);
    if (!auth)
    {
        callback(ticketing::makeErrorResponse(drogon::k401Unauthorized,
                                              "UNAUTHENTICATED",
                                              "Authentication required"));
        return;
    }
    auto done = std::make_shared<HttpCallback>(std::move(callback));
    service_.logout(
        auth->sessionId, auth->tokenHash,
        [done](bool succeeded) {
            if (!succeeded)
            {
                (*done)(ticketing::makeErrorResponse(
                    drogon::k503ServiceUnavailable, "AUTH_UNAVAILABLE",
                    "Authentication service unavailable"));
                return;
            }
            Json::Value body;
            body["status"] = "ok";
            auto response = drogon::HttpResponse::newHttpJsonResponse(body);
            ticketing::clearAuthCookies(response);
            (*done)(response);
        });
}
