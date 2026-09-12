#include "services/SeatAvailabilityReadModel.h"
#include "services/CheckoutOwnershipCache.h"
#include <charconv>
#include <cstdint>
#include "controllers/SeatController.h"

#include "common/ApiResponse.h"
#include "security/AuthConfig.h"
#include "observability/PerformanceMetrics.h"

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
    resolveOwnCheckout(
        request, sessionId,
        [this, sessionId, callbackPtr](
            std::string ownCheckoutSessionId) {
            listWithOwnCheckout(sessionId, ownCheckoutSessionId, callbackPtr);
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR",
                "Internal server error"));
        });
}

void SeatController::listSeatLayout(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string sessionId) const
{
    (void)request;
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.listSeatLayout(
        sessionId,
        [sessionId, callbackPtr](
            ticketing::SeatService::LayoutResult seats) {
            if (!seats)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "SESSION_NOT_FOUND",
                    "Session not found"));
                return;
            }
            using Metrics = ticketing::PerformanceMetrics;
            const auto started = Metrics::seatMapStart();
            Json::Value body;
            body["sessionId"] = sessionId;
            body["seats"] = Json::Value{Json::arrayValue};
            for (const auto &seat : *seats) body["seats"].append(seat.toJson());
            Metrics::observeSeatMap(Metrics::SeatMapStage::LayoutJsonBuild,
                                    started);
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR",
                "Internal server error"));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k503ServiceUnavailable, "SEAT_MAP_BUSY",
                "Seat map compute capacity exhausted"));
        });
}

void SeatController::listSeatAvailability(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string sessionId) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    if (request->getParameters().count("zone"))
    {
        const auto zone=request->getParameter("zone");
        const auto generation=request->getParameter("generation");
        const auto since=request->getParameter("since");
        const bool hasGeneration=request->getParameters().count("generation");
        const bool hasSince=request->getParameters().count("since");
        auto validCursor=[](const std::string &value){
            const auto split=value.find('-');
            if(split==std::string::npos || split==0 || split+1==value.size())return false;
            for(const auto part:{std::string_view(value).substr(0,split),std::string_view(value).substr(split+1)})
            {
                if(part.size()>1 && part.front()=='0')return false;
                std::uint64_t number{};
                const auto parsed=std::from_chars(part.data(),part.data()+part.size(),number);
                if(parsed.ec!=std::errc{} || parsed.ptr!=part.data()+part.size())return false;
            }
            return true;
        };
        if(hasGeneration!=hasSince || (hasSince && (generation.empty() || !validCursor(since))))
        {
            (*callbackPtr)(ticketing::makeErrorResponse(drogon::k400BadRequest,"INVALID_ARGUMENT","generation and valid since must be supplied together"));
            return;
        }
        resolveOwnCheckout(request,sessionId,
            [sessionId,zone,generation,since,callbackPtr](std::string own){
                ticketing::SeatAvailabilityReadModel::read(sessionId,zone,std::move(own),generation,since,*callbackPtr);
            },[callbackPtr]{(*callbackPtr)(ticketing::makeErrorResponse(drogon::k500InternalServerError,"INTERNAL_ERROR","Internal server error"));});
        return;
    }
    resolveOwnCheckout(
        request, sessionId,
        [this, sessionId, callbackPtr](
            std::string ownCheckoutSessionId) {
            listAvailabilityWithOwnCheckout(
                sessionId, ownCheckoutSessionId, callbackPtr);
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR",
                "Internal server error"));
        });
}

void SeatController::resolveOwnCheckout(
    const drogon::HttpRequestPtr &request,
    std::string sessionId,
    std::function<void(std::string)> onResolved,
    std::function<void()> onError) const
{
    const auto checkoutSessionId = request->getParameter("checkoutSessionId");
    if (checkoutSessionId.empty())
    {
        onResolved({});
        return;
    }
    const auto rawToken = request->getCookie(
        ticketing::AuthConfig::load().cookieName);
    if (rawToken.empty())
    {
        onResolved({});
        return;
    }
    authService_.authenticate(
        rawToken,
        [this, sessionId = std::move(sessionId), checkoutSessionId,
         onResolved = std::move(onResolved),
         onError = std::move(onError)](ticketing::AuthenticateResult auth) mutable {
            if (auth.outcome != ticketing::AuthenticateOutcome::Authenticated ||
                !auth.session)
            {
                onResolved({});
                return;
            }
            const auto userId=auth.session->userId;
            auto onCacheHit=onResolved;
            ticketing::CheckoutOwnershipCache::lookup(checkoutSessionId,userId,sessionId,std::move(onCacheHit),
                [this,sessionId,checkoutSessionId,userId,onResolved=std::move(onResolved),onError=std::move(onError)]() mutable {
            checkoutRepository_.findByIdForUser(
                drogon::app().getDbClient(), checkoutSessionId,
                userId,
                [sessionId, checkoutSessionId, userId,
                 onResolved = std::move(onResolved)](
                    std::optional<ticketing::CheckoutSessionRecord> checkout) mutable {
                    const bool ownsRequestedSession =
                        checkout && checkout->value.sessionId == sessionId;
                    if (ownsRequestedSession) ticketing::CheckoutOwnershipCache::store(checkoutSessionId,userId,sessionId);
                    onResolved(ownsRequestedSession ? checkoutSessionId
                                                    : std::string{});
                },
                std::move(onError));
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

            using Metrics = ticketing::PerformanceMetrics;
            const auto jsonStarted = Metrics::seatMapStart();
            Json::Value body{Json::arrayValue};
            for (const auto &seat : *seats)
            {
                body.append(seat.toJson());
            }
            Metrics::observeSeatMap(Metrics::SeatMapStage::JsonBuild, jsonStarted);
            const auto responseStarted = Metrics::seatMapStart();
            auto response = drogon::HttpResponse::newHttpJsonResponse(body);
            Metrics::observeSeatMap(Metrics::SeatMapStage::ResponseCreate, responseStarted);
            // Leave lazy serialization to Drogon's ordinary send path.
            // Body sizes are measured by an out-of-load HTTP encoding probe.
            const auto callbackStarted = Metrics::seatMapStart();
            (*callbackPtr)(response);
            // Includes synchronous framework work (e.g. compression), NOT a
            // socket-flush completion measurement.
            Metrics::observeSeatMap(Metrics::SeatMapStage::ResponseCallback, callbackStarted);
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error"));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k503ServiceUnavailable,
                "SEAT_MAP_BUSY",
                "Seat map compute capacity exhausted"));
        });
}

void SeatController::listAvailabilityWithOwnCheckout(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::shared_ptr<HttpCallback> &callbackPtr) const
{
    service_.listSeatAvailability(
        sessionId,
        checkoutSessionId,
        [sessionId, callbackPtr](
            ticketing::SeatService::AvailabilityResult seats) {
            if (!seats)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "SESSION_NOT_FOUND",
                    "Session not found"));
                return;
            }
            using Metrics = ticketing::PerformanceMetrics;
            const auto started = Metrics::seatMapStart();
            Json::Value body;
            body["sessionId"] = sessionId;
            body["seats"] = Json::Value{Json::arrayValue};
            for (const auto &seat : *seats) body["seats"].append(seat.toJson());
            Metrics::observeSeatMap(
                Metrics::SeatMapStage::AvailabilityJsonBuild, started);
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR",
                "Internal server error"));
        },
        [callbackPtr] {
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k503ServiceUnavailable, "SEAT_MAP_BUSY",
                "Seat map compute capacity exhausted"));
        });
}
