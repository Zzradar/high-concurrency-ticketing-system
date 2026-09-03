#include "controllers/SessionController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
}

void SessionController::listEventSessions(
    const drogon::HttpRequestPtr &,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string eventId) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listEventSessions(
        eventId,
        [callbackPtr](ticketing::SessionService::SessionsResult sessions) {
            if (!sessions)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound,
                    "EVENT_NOT_FOUND",
                    "Event not found"));
                return;
            }

            Json::Value body{Json::arrayValue};
            for (const auto &session : *sessions)
            {
                body.append(session.toJson());
            }
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error"));
        });
}

void SessionController::getSession(
    const drogon::HttpRequestPtr &,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string sessionId) const
{
    auto done = std::make_shared<HttpCallback>(std::move(callback));
    service_.getSession(
        sessionId,
        [done](std::optional<ticketing::TicketSession> session) {
            if (!session)
            {
                (*done)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "SESSION_NOT_FOUND",
                    "Session not found"));
                return;
            }
            (*done)(drogon::HttpResponse::newHttpJsonResponse(session->toJson()));
        },
        [done] {
            (*done)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR",
                "Internal server error"));
        });
}
