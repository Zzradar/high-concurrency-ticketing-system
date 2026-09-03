#include "security/AuthConfig.h"

#include <drogon/drogon.h>

#include <limits>
#include <stdexcept>

namespace
{
std::int64_t positiveInt64(const Json::Value &value, const char *name)
{
    if (!value.isInt64() || value.asInt64() <= 0)
    {
        throw std::runtime_error(std::string{name} + " must be a positive integer");
    }
    return value.asInt64();
}

std::size_t positiveSize(const Json::Value &value, const char *name)
{
    const auto parsed = positiveInt64(value, name);
    if (static_cast<std::uint64_t>(parsed) >
        std::numeric_limits<std::size_t>::max())
    {
        throw std::runtime_error(std::string{name} + " is too large");
    }
    return static_cast<std::size_t>(parsed);
}

std::uint32_t positiveUint32(const Json::Value &value, const char *name)
{
    const auto parsed = positiveInt64(value, name);
    if (parsed > std::numeric_limits<std::uint32_t>::max())
    {
        throw std::runtime_error(std::string{name} + " is too large");
    }
    return static_cast<std::uint32_t>(parsed);
}

std::string requiredString(const Json::Value &value, const char *name)
{
    if (!value.isString() || value.asString().empty())
    {
        throw std::runtime_error(std::string{name} + " must be a non-empty string");
    }
    return value.asString();
}
}  // namespace

namespace ticketing
{
AuthConfig AuthConfig::load()
{
    const auto &root = drogon::app().getCustomConfig();
    const auto &auth = root["authentication"];
    const auto &rate = root["login_rate_limit"];
    if (!auth.isObject() || !rate.isObject())
    {
        throw std::runtime_error("authentication and login_rate_limit config are required");
    }

    AuthConfig result{
        .idleTimeoutSeconds = positiveInt64(auth["idle_timeout_seconds"], "authentication.idle_timeout_seconds"),
        .absoluteTimeoutSeconds = positiveInt64(auth["absolute_timeout_seconds"], "authentication.absolute_timeout_seconds"),
        .sessionCacheTtlSeconds = positiveInt64(auth["session_cache_ttl_seconds"], "authentication.session_cache_ttl_seconds"),
        .lastSeenWriteIntervalSeconds = positiveInt64(auth["last_seen_write_interval_seconds"], "authentication.last_seen_write_interval_seconds"),
        .cookieName = requiredString(auth["cookie_name"], "authentication.cookie_name"),
        .csrfCookieName = requiredString(auth["csrf_cookie_name"], "authentication.csrf_cookie_name"),
        .cookieSecure = auth["cookie_secure"].asBool(),
        .allowedOrigins = {},
        .passwordHashWorkers = positiveSize(auth["password_hash_workers"], "authentication.password_hash_workers"),
        .passwordHashQueueCapacity = positiveSize(auth["password_hash_queue_capacity"], "authentication.password_hash_queue_capacity"),
        .argon2TimeCost = positiveUint32(auth["argon2_time_cost"], "authentication.argon2_time_cost"),
        .argon2MemoryCostKib = positiveUint32(auth["argon2_memory_cost_kib"], "authentication.argon2_memory_cost_kib"),
        .argon2Parallelism = positiveUint32(auth["argon2_parallelism"], "authentication.argon2_parallelism"),
        .loginRateWindowSeconds = positiveInt64(rate["window_seconds"], "login_rate_limit.window_seconds"),
        .loginRateMaxFailures = positiveInt64(rate["max_failures"], "login_rate_limit.max_failures"),
    };
    if (!auth["cookie_secure"].isBool() || !auth["allowed_origins"].isArray())
    {
        throw std::runtime_error("authentication cookie/origin config is invalid");
    }
    for (const auto &origin : auth["allowed_origins"])
    {
        result.allowedOrigins.push_back(requiredString(origin, "authentication.allowed_origins[]"));
    }
    if (result.allowedOrigins.empty() ||
        result.idleTimeoutSeconds > result.absoluteTimeoutSeconds)
    {
        throw std::runtime_error("authentication timeout/origin config is invalid");
    }
    return result;
}

void AuthConfig::validate()
{
    static_cast<void>(load());
    static_cast<void>(drogon::app().getRedisClient("auth_sessions"));
}
}  // namespace ticketing
