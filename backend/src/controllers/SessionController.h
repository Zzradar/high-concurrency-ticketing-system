#pragma once

#include "services/SessionService.h"

#include <drogon/HttpController.h>

#include <string>

class SessionController final
    : public drogon::HttpController<SessionController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(SessionController::listEventSessions,
                  "/events/{eventId}/sessions",
                  drogon::Get);
    ADD_METHOD_TO(SessionController::getSession,
                  "/sessions/{sessionId}",
                  drogon::Get);
    METHOD_LIST_END

    void listEventSessions(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string eventId) const;
    void getSession(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string sessionId) const;

  private:
    ticketing::SessionService service_;
};
