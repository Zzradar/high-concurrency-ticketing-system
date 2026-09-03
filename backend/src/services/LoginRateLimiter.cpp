#include "services/LoginRateLimiter.h"

#include "security/AuthConfig.h"

#include <drogon/drogon.h>

#include <charconv>
#include <memory>
#include <utility>

namespace
{
constexpr std::string_view kRecordFailureScript = R"lua(
for _, key in ipairs(KEYS) do
  local value = redis.call('INCR', key)
  if value == 1 then redis.call('EXPIRE', key, ARGV[1]) end
end
return 1
)lua";

std::int64_t counter(const drogon::nosql::RedisResult &value)
{
    if (value.isNil()) return 0;
    const auto text = value.asString();
    std::int64_t parsed{};
    const auto result = std::from_chars(text.data(), text.data() + text.size(), parsed);
    return result.ec == std::errc{} ? parsed : 0;
}
}  // namespace

namespace ticketing
{
std::string LoginRateLimiter::usernameKey(const std::string &username)
{
    return "ticketing:login-fail:username:" + username;
}

std::string LoginRateLimiter::ipKey(const std::string &peerIp)
{
    return "ticketing:login-fail:ip:" + peerIp;
}

void LoginRateLimiter::check(const std::string &username,
                             const std::string &peerIp,
                             std::function<void(bool)> completion) const
{
    auto done = std::make_shared<decltype(completion)>(std::move(completion));
    const auto usernameCounter = usernameKey(username);
    const auto ipCounter = ipKey(peerIp);
    const auto maxFailures = AuthConfig::load().loginRateMaxFailures;
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [done, maxFailures](const drogon::nosql::RedisResult &result) {
                try
                {
                    const auto values = result.asArray();
                    (*done)(values.size() == 2 &&
                            counter(values[0]) < maxFailures &&
                            counter(values[1]) < maxFailures);
                }
                catch (const std::exception &error)
                {
                    LOG_WARN << "Login rate-limit read failed open: " << error.what();
                    (*done)(true);
                }
            },
            [done](const std::exception &error) {
                LOG_WARN << "Login rate-limit read failed open: " << error.what();
                (*done)(true);
            },
            "MGET %s %s", usernameCounter.c_str(), ipCounter.c_str());
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Login rate-limit read failed open: " << error.what();
        (*done)(true);
    }
}

void LoginRateLimiter::recordFailure(
    const std::string &username,
    const std::string &peerIp,
    std::function<void()> completion) const
{
    auto done = std::make_shared<decltype(completion)>(std::move(completion));
    const auto usernameCounter = usernameKey(username);
    const auto ipCounter = ipKey(peerIp);
    const auto window = AuthConfig::load().loginRateWindowSeconds;
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [done](const drogon::nosql::RedisResult &) { (*done)(); },
            [done](const std::exception &error) {
                LOG_WARN << "Login rate-limit write failed open: " << error.what();
                (*done)();
            },
            "EVAL %b 2 %s %s %lld", kRecordFailureScript.data(),
            kRecordFailureScript.size(), usernameCounter.c_str(),
            ipCounter.c_str(), static_cast<long long>(window));
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Login rate-limit write failed open: " << error.what();
        (*done)();
    }
}

void LoginRateLimiter::clearUsername(const std::string &username) const
{
    const auto key = usernameKey(username);
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [](const drogon::nosql::RedisResult &) {},
            [](const std::exception &error) {
                LOG_WARN << "Login rate-limit clear failed: " << error.what();
            },
            "DEL %s", key.c_str());
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Login rate-limit clear failed: " << error.what();
    }
}
}  // namespace ticketing
