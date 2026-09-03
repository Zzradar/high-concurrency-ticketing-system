#include "controllers/SeatController.h"

#include "common/ApiResponse.h"
#include "security/AuthConfig.h"

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
    const auto checkoutSessionId = request->getParameter("checkoutSessionId");
    if (checkoutSessionId.empty())
    {
        listWithOwnCheckout(sessionId, {}, callbackPtr);
        return;
    }
    const auto rawToken = request->getCookie(
        ticketing::AuthConfig::load().cookieName);
    if (rawToken.empty())
    {
        listWithOwnCheckout(sessionId, {}, callbackPtr);
        return;
    }
    authService_.authenticate(
        rawToken,
        [this, sessionId = std::move(sessionId), checkoutSessionId,
         callbackPtr](ticketing::AuthenticateResult auth) {
            if (auth.outcome != ticketing::AuthenticateOutcome::Authenticated ||
                !auth.session)
            {
                listWithOwnCheckout(sessionId, {}, callbackPtr);
                return;
            }
            checkoutRepository_.findByIdForUser(
                drogon::app().getDbClient(), checkoutSessionId,
                auth.session->userId,
                [this, sessionId, checkoutSessionId, callbackPtr](
                    std::optional<ticketing::CheckoutSessionRecord> checkout) {
                    const bool ownsRequestedSession =
                        checkout && checkout->value.sessionId == sessionId;
                    listWithOwnCheckout(sessionId,
                                        ownsRequestedSession
                                            ? checkoutSessionId
                                            : std::string{},
                                        callbackPtr);
                },
                [callbackPtr] {
                    (*callbackPtr)(ticketing::makeErrorResponse(
                        drogon::k500InternalServerError, "INTERNAL_ERROR",
                        "Internal server error"));
                });
        });
}

void SeatController::listWithOwnCheckout(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::shared_ptr<HttpCallback> &callbackPtr) const
{
    service_.listSessionSeats(
        sessionId,
        checkoutSessionId,
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
