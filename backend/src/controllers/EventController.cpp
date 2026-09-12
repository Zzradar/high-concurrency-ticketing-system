#include "admission/PublicAdmissionSummary.h"
#include "admission/TrafficControl.h"
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
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::PublicStaticRead,std::move(callback));
    if(!trafficReply)return;
    callback=std::move(*trafficReply);

    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listEvents(
        [callbackPtr](std::vector<ticketing::TicketEvent> events) {
            Json::Value body{Json::arrayValue};
            for (const auto &event : events)
            {
                body.append(ticketing::admission::withPublicAdmission(event.toJson(),event.id));
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
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::PublicStaticRead,std::move(callback));
    if(!trafficReply)return;
    callback=std::move(*trafficReply);

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
                drogon::HttpResponse::newHttpJsonResponse(ticketing::admission::withPublicAdmission(event->toJson(),event->id)));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error"));
        });
}
