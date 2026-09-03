#include "controllers/NotificationController.h"

#include "common/ApiResponse.h"
#include "common/AuthContext.h"

#include <memory>
#include <utility>

namespace
{
using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;

void sendNotificationError(const std::shared_ptr<HttpCallback> &callback,
                           ticketing::NotificationOutcome outcome)
{
    if (outcome == ticketing::NotificationOutcome::InvalidArgument)
        (*callback)(ticketing::makeErrorResponse(
            drogon::k400BadRequest, "INVALID_ARGUMENT", "Invalid notification request"));
    else if (outcome == ticketing::NotificationOutcome::NotFound)
        (*callback)(ticketing::makeErrorResponse(
            drogon::k404NotFound, "NOTIFICATION_NOT_FOUND", "Notification not found"));
    else
        (*callback)(ticketing::makeErrorResponse(
            drogon::k500InternalServerError, "INTERNAL_ERROR", "Internal server error"));
}
}  // namespace

void NotificationController::list(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.list(
        ticketing::authenticatedUserId(request),
        [callbackPtr](ticketing::NotificationListResult result) {
            if (result.outcome != ticketing::NotificationOutcome::Found)
            {
                sendNotificationError(callbackPtr, result.outcome);
                return;
            }
            Json::Value body{Json::arrayValue};
            for (const auto &value : result.values) body.append(value.toJson());
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        });
}

void NotificationController::markRead(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string notificationId) const
{
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.markRead(
        std::move(notificationId), ticketing::authenticatedUserId(request),
        [callbackPtr](ticketing::NotificationResult result) {
            if (result.outcome == ticketing::NotificationOutcome::Found && result.value)
            {
                (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(
                    result.value->toJson()));
                return;
            }
            sendNotificationError(callbackPtr, result.outcome);
        });
}
