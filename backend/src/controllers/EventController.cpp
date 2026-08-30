#include "controllers/EventController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
}

void EventController::listEvents(
    const drogon::HttpRequestPtr &,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listEvents(
        [callbackPtr](std::vector<ticketing::TicketEvent> events) {
            Json::Value body{Json::arrayValue};
            for (const auto &event : events)
            {
                body.append(event.toJson());
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

void EventController::getEvent(
    const drogon::HttpRequestPtr &,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string eventId) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.getEvent(
        eventId,
        [callbackPtr](std::optional<ticketing::TicketEvent> event) {
            if (!event)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound,
                    "EVENT_NOT_FOUND",
                    "Event not found"));
                return;
            }
            (*callbackPtr)(
                drogon::HttpResponse::newHttpJsonResponse(event->toJson()));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error"));
        });
}
