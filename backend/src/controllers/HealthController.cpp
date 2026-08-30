#include "controllers/HealthController.h"

#include <drogon/drogon.h>

#include <memory>
#include <utility>

void HealthController::health(
    const drogon::HttpRequestPtr &,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    using Callback = std::function<void(const drogon::HttpResponsePtr &)>;
    auto callbackPtr = std::make_shared<Callback>(std::move(callback));
    auto database = drogon::app().getDbClient("default");

    database->execSqlAsync(
        "SELECT 1",
        [callbackPtr](const drogon::orm::Result &) {
            Json::Value body;
            body["status"] = "ok";
            body["database"] = "up";
            (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(body));
        },
        [callbackPtr](const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "PostgreSQL health check failed: " << error.base().what();
            Json::Value body;
            body["status"] = "degraded";
            body["database"] = "down";
            auto response = drogon::HttpResponse::newHttpJsonResponse(body);
            response->setStatusCode(drogon::k503ServiceUnavailable);
            (*callbackPtr)(response);
        });
}
