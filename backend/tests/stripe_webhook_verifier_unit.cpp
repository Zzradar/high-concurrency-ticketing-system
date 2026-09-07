#include "payments/StripeWebhookVerifier.h"
#include "security/Crypto.h"

#include <cassert>
#include <string>

int main()
{
    constexpr auto now = 1800000000LL;
    const std::string secret = "whsec_test_only";
    const std::string body = R"({"id":"evt_1","type":"payment_intent.succeeded"})";
    const auto valid = ticketing::hmacSha256Hex(
        secret, std::to_string(now) + "." + body);
    assert(ticketing::StripeWebhookVerifier::verify(
        body, "t=" + std::to_string(now) + ",v1=" + valid, secret, now));
    assert(!ticketing::StripeWebhookVerifier::verify(
        body, "t=" + std::to_string(now) + ",v1=bad", secret, now));
    assert(ticketing::StripeWebhookVerifier::verify(
        body, "t=" + std::to_string(now) + ",v1=bad,v1=" + valid, secret, now));
    assert(!ticketing::StripeWebhookVerifier::verify(
        body, "t=" + std::to_string(now) + ",v0=" + valid + ",v1=bad", secret, now));
    assert(!ticketing::StripeWebhookVerifier::verify(
        body, "t=" + std::to_string(now - 301) + ",v1=" + valid, secret, now));
    assert(!ticketing::StripeWebhookVerifier::verify(
        body + " ", "t=" + std::to_string(now) + ",v1=" + valid, secret, now));
}
