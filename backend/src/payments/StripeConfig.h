#pragma once

#include <string>

namespace ticketing
{
struct StripeConfig
{
    static constexpr const char *kApiVersion = "2026-07-29.dahlia";
    std::string secretKey;
    std::string webhookSecret;
    std::string currency{"cny"};
    std::string apiBaseUrl{"https://api.stripe.com"};
    double timeoutSeconds{5.0};

    static StripeConfig load();
    static void validate(const StripeConfig &config);
};
}  // namespace ticketing
