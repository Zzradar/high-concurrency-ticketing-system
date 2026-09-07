#pragma once

#include <cstdint>
#include <string_view>

namespace ticketing
{
class StripeWebhookVerifier
{
  public:
    static constexpr std::int64_t kToleranceSeconds = 300;
    static bool verify(std::string_view rawBody, std::string_view signatureHeader,
                       std::string_view secret, std::int64_t nowSeconds,
                       std::int64_t toleranceSeconds = kToleranceSeconds);
};
}  // namespace ticketing
