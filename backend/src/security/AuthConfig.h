#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace ticketing
{
struct AuthConfig
{
    std::int64_t idleTimeoutSeconds{};
    std::int64_t absoluteTimeoutSeconds{};
    std::int64_t sessionCacheTtlSeconds{};
    std::int64_t lastSeenWriteIntervalSeconds{};
    std::string cookieName;
    std::string csrfCookieName;
    bool cookieSecure{};
    std::vector<std::string> allowedOrigins;
    std::size_t passwordHashWorkers{};
    std::size_t passwordHashQueueCapacity{};
    std::uint32_t argon2TimeCost{};
    std::uint32_t argon2MemoryCostKib{};
    std::uint32_t argon2Parallelism{};
    std::int64_t loginRateWindowSeconds{};
    std::int64_t loginRateMaxFailures{};

    static AuthConfig load();
    static void validate();
};
}  // namespace ticketing
