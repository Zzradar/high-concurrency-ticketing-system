#include "admission/TrafficControl.h"
#include "controllers/StripeWebhookController.h"

#include "common/ApiResponse.h"
#include "payments/StripeConfig.h"
#include "payments/StripeWebhookVerifier.h"
#include "security/Crypto.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <chrono>
#include <memory>

void StripeWebhookController::receive(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
{
    auto trafficReply=ticketing::admission::TrafficControl::wrap(ticketing::admission::Resource::Financial,std::move(callback));
    if(!trafficReply)return;
    callback=std::move(*trafficReply);

    const std::string rawBody{request->body()};
    const auto signature = request->getHeader("Stripe-Signature");
    const auto config = ticketing::StripeConfig::load();
    const auto now = std::chrono::duration_cast<std::chrono::seconds>(
                         std::chrono::system_clock::now().time_since_epoch()).count();
    if (!ticketing::StripeWebhookVerifier::verify(
            rawBody, signature, config.webhookSecret, now))
    {
        ticketing::PerformanceMetrics::observePaymentWebhook("stripe", "invalid_signature");
        callback(ticketing::makeErrorResponse(
            drogon::k400BadRequest, "INVALID_WEBHOOK_SIGNATURE",
            "Invalid Stripe webhook signature"));
        return;
    }

    Json::CharReaderBuilder builder;
    std::unique_ptr<Json::CharReader> reader{builder.newCharReader()};
    Json::Value event;
    std::string errors;
    if (!reader->parse(rawBody.data(), rawBody.data() + rawBody.size(), &event, &errors) ||
        !event["id"].isString() || !event["type"].isString() ||
        !event["data"]["object"].isObject())
    {
        ticketing::PerformanceMetrics::observePaymentWebhook("stripe", "invalid_event");
        callback(ticketing::makeErrorResponse(
            drogon::k400BadRequest, "INVALID_WEBHOOK_EVENT",
            "Invalid Stripe webhook event"));
        return;
    }
    const auto &object = event["data"]["object"];
    const auto objectType = object["object"].asString();
    if (objectType != "payment_intent" && objectType != "refund")
    {
        callback(ticketing::makeErrorResponse(
            drogon::k400BadRequest, "UNSUPPORTED_WEBHOOK_EVENT",
            "Unsupported Stripe webhook object"));
        return;
    }
    const char *metadataKey = objectType == "payment_intent"
                                  ? "local_payment_attempt_id" : "local_refund_id";
    ticketing::ProviderEventRecord record{
        .id = "PVE-" + drogon::utils::getUuid(true),
        .provider = "stripe",
        .providerEventId = event["id"].asString(),
        .eventType = event["type"].asString(),
        .objectKind = objectType == "payment_intent" ? "PAYMENT" : "REFUND",
        .providerObjectId = object["id"].asString(),
        .localReferenceId = object["metadata"][metadataKey].asString(),
        .payloadSha256 = ticketing::sha256Hex(rawBody),
    };
    using Callback = std::function<void(const drogon::HttpResponsePtr &)>;
    auto done = std::make_shared<Callback>(std::move(callback));
    repository_.insert(
        drogon::app().getDbClient("default"), std::move(record),
        [done](bool inserted) {
            ticketing::PerformanceMetrics::observePaymentWebhook(
                "stripe", inserted ? "accepted" : "duplicate");
            Json::Value body;
            body["received"] = true;
            (*done)(drogon::HttpResponse::newHttpJsonResponse(body));
        },
        [done] {
            ticketing::PerformanceMetrics::observePaymentWebhook("stripe", "inbox_error");
            (*done)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "WEBHOOK_INBOX_UNAVAILABLE",
                "Webhook inbox unavailable"));
        });
}
