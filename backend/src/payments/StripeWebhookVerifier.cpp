#include "payments/StripeWebhookVerifier.h"

#include "security/Crypto.h"

#include <charconv>
#include <cstdlib>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
bool StripeWebhookVerifier::verify(std::string_view rawBody,
                                   std::string_view signatureHeader,
                                   std::string_view secret,
                                   std::int64_t nowSeconds,
                                   std::int64_t toleranceSeconds)
{
    if (secret.empty() || toleranceSeconds <= 0) return false;
    std::optional<std::int64_t> timestamp;
    std::vector<std::string_view> signatures;
    std::size_t start = 0;
    while (start <= signatureHeader.size())
    {
        const auto end = signatureHeader.find(',', start);
        auto item = signatureHeader.substr(start, end == std::string_view::npos
                                                      ? signatureHeader.size() - start
                                                      : end - start);
        const auto equals = item.find('=');
        if (equals != std::string_view::npos)
        {
            const auto name = item.substr(0, equals);
            const auto value = item.substr(equals + 1);
            if (name == "t")
            {
                std::int64_t parsed{};
                const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
                if (result.ec == std::errc{} && result.ptr == value.data() + value.size()) timestamp = parsed;
            }
            else if (name == "v1") signatures.push_back(value);
        }
        if (end == std::string_view::npos) break;
        start = end + 1;
    }
    if (!timestamp || signatures.empty() || std::llabs(nowSeconds - *timestamp) > toleranceSeconds)
        return false;
    const auto expected = hmacSha256Hex(secret, std::to_string(*timestamp) + "." + std::string{rawBody});
    for (const auto signature : signatures)
        if (constantTimeEqual(expected, signature)) return true;
    return false;
}
}  // namespace ticketing
