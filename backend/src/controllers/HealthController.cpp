#include "admission/AdmissionRuntime.h"
#include "controllers/HealthController.h"
#include "admission/AdmissionPolicy.h"

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
        "SELECT NOT EXISTS(SELECT 1 FROM event_admission_policies WHERE mode <> 'OFF') AS all_off",
        [callbackPtr](const drogon::orm::Result &rows) {
            if (!rows[0]["all_off"].as<bool>() && !ticketing::admission::secretAvailable()) {
                Json::Value body;body["status"]="degraded";body["code"]="ADMISSION_SECRET_UNAVAILABLE";
                auto response=drogon::HttpResponse::newHttpJsonResponse(body);
                response->setStatusCode(drogon::k503ServiceUnavailable);
                response->addHeader("Cache-Control","private, no-store");
                (*callbackPtr)(response);return;
            }
            if(!ticketing::admission::AdmissionRuntime::ready()) {
                Json::Value pending;pending["status"]="degraded";pending["code"]="ADMISSION_NOT_READY";
                auto response=drogon::HttpResponse::newHttpJsonResponse(pending);response->setStatusCode(drogon::k503ServiceUnavailable);(*callbackPtr)(response);return;
            }
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
