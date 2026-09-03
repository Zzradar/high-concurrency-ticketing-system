#include "controllers/SeatController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
}

void SeatController::listSessionSeats(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string sessionId) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listSessionSeats(
        sessionId,
        request->getParameter("checkoutSessionId"),
        [callbackPtr](ticketing::SeatService::SeatsResult seats) {
            if (!seats)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound,
                    "SESSION_NOT_FOUND",
                    "Session not found"));
                return;
            }

            Json::Value body{Json::arrayValue};
            for (const auto &seat : *seats)
            {
                body.append(seat.toJson());
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
