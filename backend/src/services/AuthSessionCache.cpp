#include "services/AuthSessionCache.h"

#include "security/AuthConfig.h"

#include <drogon/drogon.h>

#include <algorithm>
#include <chrono>
#include <sstream>
#include <utility>

namespace
{
std::int64_t nowEpoch()
{
    return std::chrono::duration_cast<std::chrono::seconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

std::string serialize(const ticketing::AuthSessionRecord &record)
{
    Json::Value value;
    value["sessionId"] = record.sessionId;
    value["userId"] = record.userId;
    value["username"] = record.username;
    value["displayName"] = record.displayName;
    value["createdAt"] = Json::Int64(record.createdAtEpoch);
    value["lastSeenAt"] = Json::Int64(record.lastSeenAtEpoch);
    value["idleExpiresAt"] = Json::Int64(record.idleExpiresAtEpoch);
    value["absoluteExpiresAt"] = Json::Int64(record.absoluteExpiresAtEpoch);
    Json::StreamWriterBuilder writer;
    writer["indentation"] = "";
    return Json::writeString(writer, value);
}

std::optional<ticketing::AuthSessionRecord> deserialize(
    const std::string &encoded)
{
    Json::CharReaderBuilder builder;
    Json::Value value;
    std::string errors;
    std::istringstream input{encoded};
    if (!Json::parseFromStream(builder, input, &value, &errors) ||
        !value.isObject())
    {
        return std::nullopt;
    }
    return ticketing::AuthSessionRecord{
        .sessionId = value["sessionId"].asString(),
        .userId = value["userId"].asString(),
        .username = value["username"].asString(),
        .displayName = value["displayName"].asString(),
        .createdAtEpoch = value["createdAt"].asInt64(),
        .lastSeenAtEpoch = value["lastSeenAt"].asInt64(),
        .idleExpiresAtEpoch = value["idleExpiresAt"].asInt64(),
        .absoluteExpiresAtEpoch = value["absoluteExpiresAt"].asInt64(),
    };
}
}  // namespace

namespace ticketing
{
std::string AuthSessionCache::keyFor(const std::string &tokenHash)
{
    return "ticketing:auth-session:" + tokenHash;
}

void AuthSessionCache::get(
    const std::string &tokenHash,
    std::function<void(SessionCacheResult)> completion) const
{
    auto done = std::make_shared<decltype(completion)>(std::move(completion));
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [done](const drogon::nosql::RedisResult &result) {
                try
                {
                    if (result.isNil())
                    {
                        (*done)({SessionCacheOutcome::Miss, std::nullopt});
                        return;
                    }
                    auto record = deserialize(result.asString());
                    (*done)({record ? SessionCacheOutcome::Hit
                                    : SessionCacheOutcome::Miss,
                             std::move(record)});
                }
                catch (...)
                {
                    (*done)({SessionCacheOutcome::Unavailable, std::nullopt});
                }
            },
            [done](const std::exception &error) {
                LOG_WARN << "Authentication session cache read failed: "
                         << error.what();
                (*done)({SessionCacheOutcome::Unavailable, std::nullopt});
            },
            "GET %s", keyFor(tokenHash).c_str());
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Authentication session cache read failed: " << error.what();
        (*done)({SessionCacheOutcome::Unavailable, std::nullopt});
    }
}

void AuthSessionCache::put(const std::string &tokenHash,
                           const AuthSessionRecord &record) const
{
    const auto config = AuthConfig::load();
    const auto remaining = std::min(record.idleExpiresAtEpoch - nowEpoch(),
                                    record.absoluteExpiresAtEpoch - nowEpoch());
    const auto ttl = std::min(config.sessionCacheTtlSeconds, remaining);
    if (ttl <= 0) return;
    const auto key = keyFor(tokenHash);
    const auto value = serialize(record);
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [](const drogon::nosql::RedisResult &) {},
            [](const std::exception &error) {
                LOG_WARN << "Authentication session cache write failed: "
                         << error.what();
            },
            "SET %s %b EX %lld", key.c_str(), value.data(), value.size(),
            static_cast<long long>(ttl));
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Authentication session cache write failed: " << error.what();
    }
}

void AuthSessionCache::remove(const std::string &tokenHash) const
{
    const auto key = keyFor(tokenHash);
    try
    {
        drogon::app().getRedisClient("auth_sessions")->execCommandAsync(
            [](const drogon::nosql::RedisResult &) {},
            [](const std::exception &error) {
                LOG_WARN << "Authentication session cache delete failed: "
                         << error.what();
            },
            "DEL %s", key.c_str());
    }
    catch (const std::exception &error)
    {
        LOG_WARN << "Authentication session cache delete failed: " << error.what();
    }
}
}  // namespace ticketing
