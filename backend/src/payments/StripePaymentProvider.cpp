#include "payments/StripePaymentProvider.h"

#include "payments/SimulationPaymentProvider.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <set>
#include <utility>

namespace
{
std::string envValue(const char *name, const char *fallback = "")
{
    const auto *value = std::getenv(name);
    return value && *value ? value : fallback;
}

std::string form(std::initializer_list<std::pair<std::string, std::string>> values)
{
    std::string body;
    for (const auto &[key, value] : values)
    {
        if (!body.empty()) body += '&';
        body += drogon::utils::urlEncode(key) + "=" + drogon::utils::urlEncode(value);
    }
    return body;
}

bool isRetryableStatus(drogon::HttpStatusCode status)
{
    const auto code = static_cast<int>(status);
    return code == 429 || code >= 500;
}

std::optional<std::string> jsonString(const Json::Value &value, const char *member)
{
    return value.isMember(member) && value[member].isString()
               ? std::optional<std::string>{value[member].asString()} : std::nullopt;
}

std::string safeStripeError(const Json::Value &json)
{
    if (!json.isObject() || !json["error"].isObject())
        return "STRIPE_UNKNOWN_ERROR";
    const auto &e = json["error"];
    const auto code = e["code"].isString() ? e["code"].asString() : "";
    const auto type = e["type"].isString() ? e["type"].asString() : "";
    if (code == "idempotency_key_in_use")
        return "STRIPE_RETRY";
    if (code == "charge_already_refunded" || code == "amount_too_large")
        return "STRIPE_EXTERNAL_REFUND_CONFLICT";
    if (type == "idempotency_error")
        return "STRIPE_IDEMPOTENCY_CONFLICT";
    if (type == "authentication_error" || type == "permission_error" || code == "api_key_expired")
        return "STRIPE_OPERATIONAL";
    return "STRIPE_UNKNOWN_ERROR";
}

}  // namespace

namespace ticketing
{
StripePaymentProvider::StripePaymentProvider(StripeConfig config)
    : config_(std::move(config)), client_(drogon::HttpClient::newHttpClient(config_.apiBaseUrl))
{
}

void StripePaymentProvider::request(
    drogon::HttpMethod method, std::string path, std::string body,
    std::optional<std::string> idempotencyKey, JsonCompletion completion) const
{
    const std::string operation = method == drogon::Post
        ? (path == "/v1/payment_intents" ? "create_payment" : "create_refund")
        : (path.find("/v1/payment_intents/") == 0 ? "retrieve_payment" : "retrieve_refund");
    auto request = drogon::HttpRequest::newHttpRequest();
    request->setMethod(method);
    request->setPath(std::move(path));
    request->addHeader("Authorization", "Bearer " + config_.secretKey);
    request->addHeader("Stripe-Version", StripeConfig::kApiVersion);
    if (method == drogon::Post)
    {
        request->setContentTypeCode(drogon::CT_APPLICATION_X_FORM);
        request->setBody(std::move(body));
    }
    if (idempotencyKey) request->addHeader("Idempotency-Key", *idempotencyKey);
    client_->sendRequest(
        request,
        [completion = std::move(completion), operation](drogon::ReqResult result,
                                              const drogon::HttpResponsePtr &response) {
            if (result != drogon::ReqResult::Ok || !response)
            {
                PerformanceMetrics::observePaymentProviderRequest("stripe", operation, "retryable_error");
                completion(ProviderTransportOutcome::RetryableError, nullptr,
                           "STRIPE_TRANSPORT_ERROR");
                return;
            }
            const auto json = response->getJsonObject();
            const auto code = static_cast<int>(response->statusCode());
            if (code < 200 || code >= 300)
            {
                auto error = json ? safeStripeError(*json) : "STRIPE_INVALID_JSON";
                if (isRetryableStatus(response->statusCode()) ||
                    response->getHeader("Stripe-Should-Retry") == "true")
                    error = "STRIPE_RETRY";
                else if (code == 401 || code == 403)
                    error = "STRIPE_OPERATIONAL";
                const auto outcome = isRetryableStatus(response->statusCode())
                                         ? ProviderTransportOutcome::RetryableError
                                         : ProviderTransportOutcome::PermanentError;
                PerformanceMetrics::observePaymentProviderRequest(
                    "stripe", operation, outcome == ProviderTransportOutcome::RetryableError
                                             ? "retryable_error" : "permanent_error");
                completion(outcome,
                           nullptr, error);
                return;
            }
            if (!json)
            {
                PerformanceMetrics::observePaymentProviderRequest("stripe", operation, "retryable_error");
                completion(ProviderTransportOutcome::RetryableError, nullptr,
                           "STRIPE_INVALID_JSON");
                return;
            }
            PerformanceMetrics::observePaymentProviderRequest("stripe", operation, "success");
            completion(ProviderTransportOutcome::Success, json.get(), {});
        }, config_.timeoutSeconds);
}

ProviderResult<ProviderPayment> StripePaymentProvider::mapPayment(
    const Json::Value &json, const CreatePaymentRequest &expected)
{
    if (!json.isObject() || json["object"].asString() != "payment_intent" ||
        !json["id"].isString() || !json["status"].isString())
        return {ProviderTransportOutcome::RetryableError, std::nullopt, "STRIPE_INVALID_PAYMENT"};
    if (json["amount"].asInt64() != expected.amount ||
        json["currency"].asString() != expected.currency ||
        json["metadata"]["local_payment_attempt_id"].asString() != expected.attemptId ||
        json["metadata"]["order_id"].asString() != expected.orderId)
        return {ProviderTransportOutcome::PermanentError, std::nullopt, "STRIPE_PAYMENT_MISMATCH"};

    ProviderPayment payment{.provider = "stripe",
                            .providerPaymentId = json["id"].asString(),
                            .providerStatus = json["status"].asString(),
                            .clientSecret = jsonString(json, "client_secret")};
    const auto &status = payment.providerStatus;
    if (status == "succeeded") { payment.mappedState = ProviderPaymentState::Succeeded; payment.terminal = true; }
    else if (status == "canceled") { payment.mappedState = ProviderPaymentState::Failed; payment.terminal = true; }
    else if (status == "requires_payment_method" && json["last_payment_error"].isObject())
    {
        payment.mappedState = ProviderPaymentState::Failed; payment.terminal = true;
        payment.failureCode = jsonString(json["last_payment_error"], "code");
    }
    else if (status == "requires_action" || status == "requires_confirmation" ||
             status == "requires_payment_method") payment.mappedState = ProviderPaymentState::ActionRequired;
    else payment.mappedState = ProviderPaymentState::Processing;
    return {ProviderTransportOutcome::Success, std::move(payment), {}};
}

namespace
{
ProviderResult<ProviderRefund> refundError(std::string code)
{
    auto category = ProviderFailureClass::TRANSIENT;
    if (code == "STRIPE_OPERATIONAL")
        category = ProviderFailureClass::OPERATIONAL;
    if (code.find("CONFLICT") != std::string::npos || code.find("MISMATCH") != std::string::npos ||
        code == "STRIPE_REFUND_PAGINATION")
        category = ProviderFailureClass::IDENTITY_CONFLICT;
    return {ProviderTransportOutcome::RetryableError, std::nullopt, std::move(code), category};
}
bool textEquals(const Json::Value &v, const std::string &expected)
{
    return v.isString() && v.asString() == expected;
}
} // namespace
ProviderResult<ProviderRefund> StripePaymentProvider::mapRefund(
    const Json::Value &json, const CreateRefundRequest &expected)
{
    if (!json.isObject() || !textEquals(json["object"], "refund") || !json["id"].isString() ||
        json["id"].asString().find("re_") != 0 || !json["status"].isString())
        return refundError("STRIPE_INVALID_REFUND");
    if (expected.provider != "stripe" || !json["amount"].isInt64() ||
        json["amount"].asInt64() != expected.amount ||
        !textEquals(json["currency"], expected.currency) ||
        !textEquals(json["payment_intent"], expected.providerPaymentId) ||
        !json["metadata"].isObject() ||
        !textEquals(json["metadata"]["local_refund_id"], expected.refundId) ||
        !textEquals(json["metadata"]["order_id"], expected.orderId))
        return refundError("STRIPE_REFUND_MISMATCH");
    ProviderRefund refund{.provider = "stripe",
                          .providerRefundId = json["id"].asString(),
                          .providerStatus = json["status"].asString()};
    refund.providerPaymentId = expected.providerPaymentId;
    refund.localRefundId = expected.refundId;
    refund.orderId = expected.orderId;
    refund.amount = expected.amount;
    refund.currency = expected.currency;
    if (refund.providerStatus == "succeeded") { refund.mappedState = ProviderRefundState::Succeeded; refund.terminal = true; }
    else if (refund.providerStatus == "failed" || refund.providerStatus == "canceled")
    {
        refund.mappedState = ProviderRefundState::Failed; refund.terminal = true;
        refund.failureCode = "PROVIDER_REFUND_FAILED";
    }
    else if (refund.providerStatus == "requires_action") refund.mappedState = ProviderRefundState::ActionRequired;
    return {ProviderTransportOutcome::Success, std::move(refund), {}};
}

void StripePaymentProvider::createOrRecoverPayment(
    CreatePaymentRequest input, PaymentCompletion completion)
{
    const auto body = form({{"amount", std::to_string(input.amount)},
                            {"currency", input.currency},
                            {"payment_method_types[]", "card"},
                            {"metadata[local_payment_attempt_id]", input.attemptId},
                            {"metadata[order_id]", input.orderId}});
    const auto idempotencyKey = input.attemptId;
    request(drogon::Post, "/v1/payment_intents", body, idempotencyKey,
            [input = std::move(input), completion = std::move(completion)](
                ProviderTransportOutcome outcome, const Json::Value *json, std::string error) {
                if (outcome != ProviderTransportOutcome::Success)
                    return completion({outcome, std::nullopt, std::move(error)});
                completion(mapPayment(*json, input));
            });
}

void StripePaymentProvider::retrievePayment(
    RetrievePaymentRequest input, PaymentCompletion completion)
{
    const auto providerPaymentId = input.providerPaymentId;
    request(drogon::Get, "/v1/payment_intents/" + drogon::utils::urlEncode(providerPaymentId),
            {}, std::nullopt,
            [input = std::move(input), completion = std::move(completion)](
                ProviderTransportOutcome outcome, const Json::Value *json, std::string error) {
                if (outcome != ProviderTransportOutcome::Success)
                    return completion({outcome, std::nullopt, std::move(error)});
                if ((*json)["id"].asString() != input.providerPaymentId)
                    return completion({ProviderTransportOutcome::RetryableError, std::nullopt, "STRIPE_PAYMENT_ID_MISMATCH"});
                completion(mapPayment(*json, input));
            });
}

struct StripePaymentProvider::RefundScan
{
    CreateRefundRequest input;
    RefundCompletion completion;
    unsigned pages{};
    std::string cursor;
    std::set<std::string> cursors;
    std::optional<ProviderRefund> match;
};
void StripePaymentProvider::createOrRecoverRefund(CreateRefundRequest input,
                                                  RefundCompletion completion)
{
    auto scan = std::make_shared<RefundScan>();
    scan->input = std::move(input);
    scan->completion = std::move(completion);
    scanRefunds(scan);
}
void StripePaymentProvider::scanRefunds(std::shared_ptr<RefundScan> scan)
{
    const auto path =
        "/v1/refunds?payment_intent=" + drogon::utils::urlEncode(scan->input.providerPaymentId) +
        "&limit=100" +
        (scan->cursor.empty() ? "" : "&starting_after=" + drogon::utils::urlEncode(scan->cursor));
    ++scan->pages;
    request(
        drogon::Get, path, {}, std::nullopt,
        [this, scan](ProviderTransportOutcome outcome, const Json::Value *json, std::string error) {
            if (outcome != ProviderTransportOutcome::Success)
                return scan->completion(refundError(error));
            if (!json->isObject() || !(*json)["data"].isArray() || !(*json)["has_more"].isBool() ||
                (*json)["data"].size() > 100)
                return scan->completion(refundError("STRIPE_INVALID_JSON"));
            for (const auto &candidate : (*json)["data"])
            {
                if (!candidate.isObject() || !candidate["metadata"].isObject())
                    return scan->completion(refundError("STRIPE_INVALID_JSON"));
                if (textEquals(candidate["metadata"]["local_refund_id"], scan->input.refundId))
                {
                    if (scan->match)
                        return scan->completion(refundError("STRIPE_MULTIPLE_REFUND_CONFLICT"));
                    auto mapped = mapRefund(candidate, scan->input);
                    if (!mapped.value)
                        return scan->completion(std::move(mapped));
                    scan->match = std::move(mapped.value);
                }
            }
            if ((*json)["has_more"].asBool())
            {
                const auto &data = (*json)["data"];
                if (scan->pages >= 10 || data.empty() || !data[data.size() - 1]["id"].isString())
                    return scan->completion(refundError("STRIPE_REFUND_PAGINATION"));
                auto cursor = data[data.size() - 1]["id"].asString();
                if (cursor.find("re_") != 0 || !scan->cursors.insert(cursor).second)
                    return scan->completion(refundError("STRIPE_REFUND_PAGINATION"));
                scan->cursor = cursor;
                scanRefunds(scan);
                return;
            }
            if (scan->match)
                return scan->completion(
                    {ProviderTransportOutcome::Success, std::move(scan->match), {}});
            const auto &input = scan->input;
            const auto body = form({{"payment_intent", input.providerPaymentId},
                                    {"amount", std::to_string(input.amount)},
                                    {"metadata[local_refund_id]", input.refundId},
                                    {"metadata[order_id]", input.orderId}});
            request(
                drogon::Post, "/v1/refunds", body, input.refundId,
                [scan](ProviderTransportOutcome result, const Json::Value *value, std::string err) {
                    if (result != ProviderTransportOutcome::Success)
                        return scan->completion(refundError(err));
                    scan->completion(mapRefund(*value, scan->input));
                });
        });
}
void StripePaymentProvider::retrieveRefund(RetrieveRefundRequest input, RefundCompletion completion)
{
    const auto path = "/v1/refunds/" + drogon::utils::urlEncode(input.providerRefundId);
    request(drogon::Get, path, {}, std::nullopt,
            [input = std::move(input), completion = std::move(completion)](
                ProviderTransportOutcome outcome, const Json::Value *json, std::string error) {
                if (outcome != ProviderTransportOutcome::Success)
                    return completion(refundError(error));
                if (!json->isObject() || !textEquals((*json)["id"], input.providerRefundId))
                    return completion(refundError("STRIPE_REFUND_ID_MISMATCH"));
                completion(mapRefund(*json, input));
            });
}

std::string PaymentProviderFactory::configuredProvider()
{
    auto provider = envValue("TICKETING_PAYMENT_PROVIDER", "simulation");
    std::transform(provider.begin(), provider.end(), provider.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return provider;
}

std::string PaymentProviderFactory::configuredCurrency()
{
    return envValue("STRIPE_CURRENCY", "cny");
}

void PaymentProviderFactory::validateConfiguration()
{
    const auto provider = configuredProvider();
    if (provider == "simulation") { PaymentSimulation::validateConfiguration(); return; }
    if (provider == "stripe") { const auto config = StripeConfig::load(); StripeConfig::validate(config); return; }
    throw std::invalid_argument("TICKETING_PAYMENT_PROVIDER must be simulation or stripe");
}

std::shared_ptr<PaymentProvider> PaymentProviderFactory::create()
{
    return createNamed(configuredProvider());
}

std::shared_ptr<PaymentProvider> PaymentProviderFactory::createNamed(const std::string &provider)
{
    if (provider == "simulation") return std::make_shared<SimulationPaymentProvider>();
    if (provider == "stripe") return std::make_shared<StripePaymentProvider>(StripeConfig::load());
    throw std::invalid_argument("Unknown payment provider");
}
}  // namespace ticketing
