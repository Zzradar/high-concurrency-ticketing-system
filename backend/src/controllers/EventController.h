#pragma once

#include "services/EventService.h"

#include <drogon/HttpController.h>

#include <string>

class EventController final : public drogon::HttpController<EventController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(EventController::listEvents, "/events", drogon::Get);
    ADD_METHOD_TO(EventController::getEvent, "/events/{eventId}", drogon::Get);
    METHOD_LIST_END

    void listEvents(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;

    void getEvent(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string eventId) const;

  private:
    ticketing::EventService service_;
};
