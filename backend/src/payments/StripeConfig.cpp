#include "payments/StripeConfig.h"

#include <cstdlib>
#include <cmath>
#include <stdexcept>

namespace
{
std::string environment(const char *name, const char *fallback = "")
{
    const auto *value = std::getenv(name);
    return value && *value ? value : fallback;
}
}  // namespace

namespace ticketing
{
StripeConfig StripeConfig::load()
{
    StripeConfig config;
    config.secretKey = environment("STRIPE_SECRET_KEY");
    config.webhookSecret = environment("STRIPE_WEBHOOK_SECRET");
    config.currency = environment("STRIPE_CURRENCY", "cny");
    config.apiBaseUrl = environment("STRIPE_API_BASE_URL", "https://api.stripe.com");
    if (const auto timeout = environment("STRIPE_HTTP_TIMEOUT_SECONDS"); !timeout.empty())
    {
        try { config.timeoutSeconds = std::stod(timeout); }
        catch (...) { throw std::invalid_argument("STRIPE_HTTP_TIMEOUT_SECONDS must be numeric"); }
    }
    if (const auto grace = environment("STRIPE_PROCESSING_GRACE_SECONDS"); !grace.empty())
    {
        std::size_t consumed = 0;
        try { config.processingGraceSeconds = std::stod(grace, &consumed); }
        catch (...) { throw std::invalid_argument("STRIPE_PROCESSING_GRACE_SECONDS must be a positive finite number"); }
        if (consumed != grace.size() || !std::isfinite(config.processingGraceSeconds) ||
            config.processingGraceSeconds <= 0.0)
            throw std::invalid_argument("STRIPE_PROCESSING_GRACE_SECONDS must be a positive finite number");
    }
    return config;
}

void StripeConfig::validate(const StripeConfig &config)
{
    if (config.secretKey.empty()) throw std::invalid_argument("STRIPE_SECRET_KEY is required");
    if (config.webhookSecret.empty()) throw std::invalid_argument("STRIPE_WEBHOOK_SECRET is required");
    if (config.currency.empty()) throw std::invalid_argument("STRIPE_CURRENCY must not be empty");
    if (config.apiBaseUrl.empty()) throw std::invalid_argument("STRIPE_API_BASE_URL must not be empty");
    if (config.timeoutSeconds <= 0.0) throw std::invalid_argument("Stripe HTTP timeout must be positive");
    if (!std::isfinite(config.processingGraceSeconds) || config.processingGraceSeconds <= 0.0)
        throw std::invalid_argument("STRIPE_PROCESSING_GRACE_SECONDS must be a positive finite number");
}
}  // namespace ticketing
