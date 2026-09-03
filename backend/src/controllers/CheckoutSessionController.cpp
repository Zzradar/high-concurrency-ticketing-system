#include "controllers/CheckoutSessionController.h"

#include "common/ApiResponse.h"
#include "common/AuthContext.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;

drogon::HttpResponsePtr makeCheckoutResponse(
    ticketing::CheckoutSessionResult result)
{
    using ticketing::CheckoutSessionOutcome;
    switch (result.outcome)
    {
        case CheckoutSessionOutcome::Created:
        case CheckoutSessionOutcome::Found:
        case CheckoutSessionOutcome::Updated:
        case CheckoutSessionOutcome::Confirmed:
        case CheckoutSessionOutcome::Abandoned:
            if (result.value)
            {
                auto response = drogon::HttpResponse::newHttpJsonResponse(
                    result.value->toJson());
                response->setStatusCode(
                    result.outcome == CheckoutSessionOutcome::Created
                        ? drogon::k201Created
                        : drogon::k200OK);
                return response;
            }
            break;
        case CheckoutSessionOutcome::InvalidArgument:
            return ticketing::makeErrorResponse(
                drogon::k400BadRequest,
                "INVALID_ARGUMENT",
                "Invalid checkout session request");
        case CheckoutSessionOutcome::SessionNotFound:
            return ticketing::makeErrorResponse(drogon::k404NotFound,
                                                "SESSION_NOT_FOUND",
                                                "Session not found");
        case CheckoutSessionOutcome::SessionNotAvailable:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "SESSION_NOT_AVAILABLE",
                "Session is not available for checkout");
        case CheckoutSessionOutcome::NotFound:
            return ticketing::makeErrorResponse(
                drogon::k404NotFound,
                "CHECKOUT_SESSION_NOT_FOUND",
                "Checkout session not found");
        case CheckoutSessionOutcome::NotModifiable:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "CHECKOUT_SESSION_NOT_MODIFIABLE",
                "Checkout session seats cannot be modified");
        case CheckoutSessionOutcome::VersionConflict:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "CHECKOUT_SESSION_VERSION_CONFLICT",
                "Checkout session was modified by another client");
        case CheckoutSessionOutcome::NotConfirmable:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "CHECKOUT_SESSION_NOT_CONFIRMABLE",
                "Checkout session cannot be confirmed");
        case CheckoutSessionOutcome::NotAbandonable:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "CHECKOUT_SESSION_NOT_ABANDONABLE",
                "Checkout session cannot be abandoned");
        case CheckoutSessionOutcome::SeatConflict:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "SEAT_CONFLICT",
                "Selected seats are no longer available");
        case CheckoutSessionOutcome::TemporarySeatConflict:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "SEAT_TEMPORARILY_HELD",
                "Selected seats are temporarily held by another checkout session");
        case CheckoutSessionOutcome::InternalError:
            break;
    }
    return ticketing::makeErrorResponse(drogon::k500InternalServerError,
                                        "INTERNAL_ERROR",
                                        "Internal server error");
}

void respond(const std::shared_ptr<HttpCallback> &callback,
             ticketing::CheckoutSessionResult result)
{
    (*callback)(makeCheckoutResponse(std::move(result)));
}
}  // namespace

void CheckoutSessionController::create(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    const auto json = request->getJsonObject();
    if (!json)
    {
        respond(callbackPtr,
                {ticketing::CheckoutSessionOutcome::InvalidArgument,
                 std::nullopt});
        return;
    }
    service_.create(ticketing::authenticatedUserId(request),
                    *json,
                    [callbackPtr](ticketing::CheckoutSessionResult result) {
                        respond(callbackPtr, std::move(result));
                    });
}

void CheckoutSessionController::list(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listRecoverable(
        ticketing::authenticatedUserId(request),
        request->getParameter("sessionId"),
        request->getParameter("recoverable") == "true",
        [callbackPtr](ticketing::CheckoutSessionListResult result) {
            if (result.outcome ==
                ticketing::CheckoutSessionOutcome::InvalidArgument)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k400BadRequest,
                    "INVALID_ARGUMENT",
                    "Invalid checkout session query"));
                return;
            }
            if (result.outcome != ticketing::CheckoutSessionOutcome::Found)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k500InternalServerError,
                    "INTERNAL_ERROR",
                    "Internal server error"));
                return;
            }
            Json::Value body{Json::arrayValue};
            for (const auto &value : result.values)
            {
                body.append(value.toJson());
            }
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        });
}

void CheckoutSessionController::get(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string id) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.get(std::move(id),
                 ticketing::authenticatedUserId(request),
                 [callbackPtr](ticketing::CheckoutSessionResult result) {
                     respond(callbackPtr, std::move(result));
                 });
}

void CheckoutSessionController::replaceSeats(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string id) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    const auto json = request->getJsonObject();
    if (!json)
    {
        respond(callbackPtr,
                {ticketing::CheckoutSessionOutcome::InvalidArgument,
                 std::nullopt});
        return;
    }
    service_.replaceSeats(
        std::move(id),
        ticketing::authenticatedUserId(request),
        *json,
        [callbackPtr](ticketing::CheckoutSessionResult result) {
            respond(callbackPtr, std::move(result));
        });
}

void CheckoutSessionController::confirm(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string id) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.confirm(std::move(id),
                     ticketing::authenticatedUserId(request),
                     [callbackPtr](ticketing::CheckoutSessionResult result) {
                         respond(callbackPtr, std::move(result));
                     });
}

void CheckoutSessionController::abandon(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string id) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.abandon(std::move(id),
                     ticketing::authenticatedUserId(request),
                     [callbackPtr](ticketing::CheckoutSessionResult result) {
                         respond(callbackPtr, std::move(result));
                     });
}
