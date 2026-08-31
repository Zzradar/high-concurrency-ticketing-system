#include "controllers/ReservationController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;

drogon::HttpResponsePtr makeServiceResponse(
    ticketing::CreateReservationResult result)
{
    using ticketing::CreateReservationOutcome;

    if (result.outcome == CreateReservationOutcome::Created ||
        result.outcome == CreateReservationOutcome::Replayed)
    {
        if (!result.value)
        {
            return ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error");
        }
        auto response = drogon::HttpResponse::newHttpJsonResponse(
            result.value->toJson());
        response->setStatusCode(
            result.outcome == CreateReservationOutcome::Created
                ? drogon::k201Created
                : drogon::k200OK);
        return response;
    }

    switch (result.outcome)
    {
        case CreateReservationOutcome::InvalidArgument:
            return ticketing::makeErrorResponse(
                drogon::k400BadRequest,
                "INVALID_ARGUMENT",
                "Invalid reservation request");
        case CreateReservationOutcome::SessionNotFound:
            return ticketing::makeErrorResponse(
                drogon::k404NotFound,
                "SESSION_NOT_FOUND",
                "Session not found");
        case CreateReservationOutcome::SessionNotAvailable:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "SESSION_NOT_AVAILABLE",
                "Session is not available for reservation");
        case CreateReservationOutcome::SeatConflict:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "SEAT_CONFLICT",
                "Selected seats are no longer available");
        case CreateReservationOutcome::IdempotencyConflict:
            return ticketing::makeErrorResponse(
                drogon::k409Conflict,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key was already used for a different reservation request");
        case CreateReservationOutcome::Created:
        case CreateReservationOutcome::Replayed:
        case CreateReservationOutcome::InternalError:
            return ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error");
    }

    return ticketing::makeErrorResponse(drogon::k500InternalServerError,
                                        "INTERNAL_ERROR",
                                        "Internal server error");
}
}  // namespace

void ReservationController::createReservation(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    const auto json = request->getJsonObject();
    if (!json)
    {
        (*callbackPtr)(ticketing::makeErrorResponse(
            drogon::k400BadRequest,
            "INVALID_ARGUMENT",
            "Invalid reservation request"));
        return;
    }

    service_.createReservation(
        ticketing::CreateReservationInput{
            .userId = request->getHeader("X-User-Id"),
            .idempotencyKey = request->getHeader("Idempotency-Key"),
            .body = *json,
        },
        [callbackPtr](ticketing::CreateReservationResult result) {
            (*callbackPtr)(makeServiceResponse(std::move(result)));
        });
}
