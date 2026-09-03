#include "services/SeatHoldService.h"

#include <drogon/drogon.h>

#include <charconv>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>

namespace
{
using ticketing::SeatHoldOutcome;

constexpr std::string_view kPrepareScript = R"lua(
local owner = ARGV[1]
local added_count = tonumber(ARGV[2])
local base_revision = ARGV[3]
local target_revision = ARGV[4]
local ttl = tonumber(ARGV[5])
for _, key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if value then
    local separator = string.find(value, '|', 1, true)
    if not separator then return redis.error_reply('malformed seat hold') end
    if string.sub(value, 1, separator - 1) ~= owner then return 0 end
  end
end
for index, key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if index <= added_count then
    redis.call('SET', key, owner .. '|' .. target_revision, 'EX', ttl)
  elseif not value then
    redis.call('SET', key, owner .. '|' .. base_revision, 'EX', ttl)
  else
    redis.call('EXPIRE', key, ttl)
  end
end
return 1
)lua";

constexpr std::string_view kAbortScript = R"lua(
local expected = ARGV[1] .. '|' .. ARGV[2]
local deleted = 0
for _, key in ipairs(KEYS) do
  if redis.call('GET', key) == expected then
    deleted = deleted + redis.call('DEL', key)
  end
end
return deleted
)lua";

constexpr std::string_view kFinalizeScript = R"lua(
local owner = ARGV[1]
local target_revision = tonumber(ARGV[2])
local deleted = 0
for _, key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if value then
    local separator = string.find(value, '|', 1, true)
    if not separator then return redis.error_reply('malformed seat hold') end
    local current_owner = string.sub(value, 1, separator - 1)
    local revision = tonumber(string.sub(value, separator + 1))
    if not revision then return redis.error_reply('malformed seat hold revision') end
    if current_owner == owner and revision <= target_revision then
      deleted = deleted + redis.call('DEL', key)
    end
  end
end
return deleted
)lua";

constexpr std::string_view kEnsureScript = R"lua(
local owner = ARGV[1]
local revision = ARGV[2]
local ttl = tonumber(ARGV[3])
for _, key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if value then
    local separator = string.find(value, '|', 1, true)
    if not separator then return redis.error_reply('malformed seat hold') end
    if string.sub(value, 1, separator - 1) ~= owner then return 0 end
  end
end
for _, key in ipairs(KEYS) do
  if redis.call('GET', key) then
    redis.call('EXPIRE', key, ttl)
  else
    redis.call('SET', key, owner .. '|' .. revision, 'EX', ttl)
  end
end
return 1
)lua";

constexpr std::string_view kReleaseScript = R"lua(
local owner = ARGV[1]
local deleted = 0
for _, key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if value then
    local separator = string.find(value, '|', 1, true)
    if separator and string.sub(value, 1, separator - 1) == owner then
      deleted = deleted + redis.call('DEL', key)
    end
  end
end
return deleted
)lua";

constexpr std::string_view kReadScript = R"lua(
local keys = cjson.decode(ARGV[1])
return redis.call('MGET', unpack(keys))
)lua";

std::string arguments(std::initializer_list<std::string> values)
{
    std::string result;
    for (const auto &value : values)
    {
        result += ' ';
        result += value;
    }
    return result;
}

template <typename Success, typename Error>
void executeWithKeys(
    std::string_view script,
    const std::vector<std::string> &keys,
    const std::string &arguments,
    Success &&success,
    Error &&error)
{
    auto client = drogon::app().getRedisClient("seat_holds");
    std::string command = "EVAL %b " + std::to_string(keys.size());
    for (std::size_t index = 0; index < keys.size(); ++index)
    {
        command += " %s";
    }
    command += arguments;

    switch (keys.size())
    {
        case 1:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str());
            break;
        case 2:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str(), keys[1].c_str());
            break;
        case 3:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str(), keys[1].c_str(), keys[2].c_str());
            break;
        case 4:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str(), keys[1].c_str(), keys[2].c_str(), keys[3].c_str());
            break;
        case 5:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str(), keys[1].c_str(), keys[2].c_str(), keys[3].c_str(), keys[4].c_str());
            break;
        case 6:
            client->execCommandAsync(std::forward<Success>(success), std::forward<Error>(error), command, script.data(), script.size(), keys[0].c_str(), keys[1].c_str(), keys[2].c_str(), keys[3].c_str(), keys[4].c_str(), keys[5].c_str());
            break;
        default:
            throw std::invalid_argument("seat hold operation requires one to six seats");
    }
}

std::vector<std::string> keysFor(
    const std::string &sessionId,
    const std::vector<std::string> &seatIds)
{
    std::vector<std::string> keys;
    keys.reserve(seatIds.size());
    for (const auto &seatId : seatIds)
    {
        keys.push_back(ticketing::SeatHoldService::keyFor(sessionId, seatId));
    }
    return keys;
}

std::optional<std::string> ownerFromValue(const std::string &value)
{
    const auto separator = value.rfind('|');
    if (separator == std::string::npos || separator == 0 || separator + 1 >= value.size())
    {
        throw std::runtime_error("malformed seat hold");
    }
    std::int64_t revision{};
    const auto *begin = value.data() + separator + 1;
    const auto *end = value.data() + value.size();
    const auto parsed = std::from_chars(begin, end, revision);
    if (parsed.ec != std::errc{} || parsed.ptr != end || revision < 0)
    {
        throw std::runtime_error("malformed seat hold revision");
    }
    return value.substr(0, separator);
}
}  // namespace

namespace ticketing
{
void SeatHoldService::validateConfiguration()
{
    static_cast<void>(ttlSeconds());
    static_cast<void>(drogon::app().getRedisClient("seat_holds"));
}

int SeatHoldService::ttlSeconds()
{
    const auto &config = drogon::app().getCustomConfig();
    const auto value = config["checkout_seat_hold"]["ttl_seconds"];
    if (!value.isInt64() || value.asInt64() <= 0 ||
        value.asInt64() > std::numeric_limits<int>::max())
    {
        throw std::runtime_error("custom_config.checkout_seat_hold.ttl_seconds must be a positive integer");
    }
    return static_cast<int>(value.asInt64());
}

std::string SeatHoldService::keyFor(
    const std::string &sessionId,
    const std::string &sessionSeatId)
{
    return "ticketing:seat-hold:{" + sessionId + "}:" + sessionSeatId;
}

void SeatHoldService::prepare(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::vector<std::string> &addedSeatIds,
    const std::vector<std::string> &retainedSeatIds,
    std::int64_t baseRevision,
    std::int64_t targetRevision,
    Completion completion) const
{
    if (addedSeatIds.empty() && retainedSeatIds.empty())
    {
        completion(SeatHoldOutcome::Applied);
        return;
    }
    auto allSeatIds = addedSeatIds;
    allSeatIds.insert(allSeatIds.end(), retainedSeatIds.begin(), retainedSeatIds.end());
    auto done = std::make_shared<Completion>(std::move(completion));
    try
    {
        executeWithKeys(
            kPrepareScript,
            keysFor(sessionId, allSeatIds),
            arguments({checkoutSessionId, std::to_string(addedSeatIds.size()), std::to_string(baseRevision), std::to_string(targetRevision), std::to_string(ttlSeconds())}),
            [done](const drogon::nosql::RedisResult &result) {
                try
                {
                    (*done)(result.asInteger() == 1 ? SeatHoldOutcome::Applied : SeatHoldOutcome::Conflict);
                }
                catch (...)
                {
                    (*done)(SeatHoldOutcome::Unavailable);
                }
            },
            [done](const std::exception &) { (*done)(SeatHoldOutcome::Unavailable); });
    }
    catch (...)
    {
        (*done)(SeatHoldOutcome::Unavailable);
    }
}

void SeatHoldService::abort(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::vector<std::string> &addedSeatIds,
    std::int64_t targetRevision,
    Completion completion) const
{
    if (addedSeatIds.empty())
    {
        completion(SeatHoldOutcome::Applied);
        return;
    }
    auto done = std::make_shared<Completion>(std::move(completion));
    try
    {
        executeWithKeys(
            kAbortScript,
            keysFor(sessionId, addedSeatIds),
            arguments({checkoutSessionId, std::to_string(targetRevision)}),
            [done](const drogon::nosql::RedisResult &) { (*done)(SeatHoldOutcome::Applied); },
            [done](const std::exception &) { (*done)(SeatHoldOutcome::Unavailable); });
    }
    catch (...)
    {
        (*done)(SeatHoldOutcome::Unavailable);
    }
}

void SeatHoldService::finalize(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::vector<std::string> &removedSeatIds,
    std::int64_t targetRevision,
    Completion completion) const
{
    if (removedSeatIds.empty())
    {
        completion(SeatHoldOutcome::Applied);
        return;
    }
    auto done = std::make_shared<Completion>(std::move(completion));
    try
    {
        executeWithKeys(
            kFinalizeScript,
            keysFor(sessionId, removedSeatIds),
            arguments({checkoutSessionId, std::to_string(targetRevision)}),
            [done](const drogon::nosql::RedisResult &) { (*done)(SeatHoldOutcome::Applied); },
            [done](const std::exception &) { (*done)(SeatHoldOutcome::Unavailable); });
    }
    catch (...)
    {
        (*done)(SeatHoldOutcome::Unavailable);
    }
}

void SeatHoldService::ensure(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::vector<std::string> &seatIds,
    std::int64_t revision,
    Completion completion) const
{
    if (seatIds.empty())
    {
        completion(SeatHoldOutcome::Applied);
        return;
    }
    auto done = std::make_shared<Completion>(std::move(completion));
    try
    {
        executeWithKeys(
            kEnsureScript,
            keysFor(sessionId, seatIds),
            arguments({checkoutSessionId, std::to_string(revision), std::to_string(ttlSeconds())}),
            [done](const drogon::nosql::RedisResult &result) {
                try
                {
                    (*done)(result.asInteger() == 1 ? SeatHoldOutcome::Applied : SeatHoldOutcome::Conflict);
                }
                catch (...)
                {
                    (*done)(SeatHoldOutcome::Unavailable);
                }
            },
            [done](const std::exception &) { (*done)(SeatHoldOutcome::Unavailable); });
    }
    catch (...)
    {
        (*done)(SeatHoldOutcome::Unavailable);
    }
}

void SeatHoldService::release(
    const std::string &sessionId,
    const std::string &checkoutSessionId,
    const std::vector<std::string> &seatIds,
    Completion completion) const
{
    if (seatIds.empty())
    {
        completion(SeatHoldOutcome::Applied);
        return;
    }
    auto done = std::make_shared<Completion>(std::move(completion));
    try
    {
        executeWithKeys(
            kReleaseScript,
            keysFor(sessionId, seatIds),
            arguments({checkoutSessionId}),
            [done](const drogon::nosql::RedisResult &) { (*done)(SeatHoldOutcome::Applied); },
            [done](const std::exception &) { (*done)(SeatHoldOutcome::Unavailable); });
    }
    catch (...)
    {
        (*done)(SeatHoldOutcome::Unavailable);
    }
}

void SeatHoldService::readOwners(
    const std::string &sessionId,
    const std::vector<std::string> &seatIds,
    ReadCompletion completion) const
{
    if (seatIds.empty())
    {
        completion({SeatHoldOutcome::Applied, {}});
        return;
    }
    auto done = std::make_shared<ReadCompletion>(std::move(completion));
    try
    {
        const auto keys = keysFor(sessionId, seatIds);
        Json::Value keyArray{Json::arrayValue};
        for (const auto &key : keys)
        {
            keyArray.append(key);
        }
        Json::StreamWriterBuilder writer;
        writer["indentation"] = "";
        const auto encodedKeys = Json::writeString(writer, keyArray);
        auto success = [done](const drogon::nosql::RedisResult &result) {
            try
            {
                SeatHoldReadResult read{
                    .outcome = SeatHoldOutcome::Applied,
                    .owners = {},
                };
                for (const auto &item : result.asArray())
                {
                    if (item.isNil())
                    {
                        read.owners.push_back(std::nullopt);
                    }
                    else
                    {
                        read.owners.push_back(ownerFromValue(item.asString()));
                    }
                }
                (*done)(std::move(read));
            }
            catch (...)
            {
                (*done)({SeatHoldOutcome::Unavailable, {}});
            }
        };
        auto error = [done](const std::exception &) {
            (*done)({SeatHoldOutcome::Unavailable, {}});
        };
        drogon::app().getRedisClient("seat_holds")->execCommandAsync(
            success,
            error,
            "EVAL %b 0 %b",
            kReadScript.data(),
            kReadScript.size(),
            encodedKeys.data(),
            encodedKeys.size());
    }
    catch (...)
    {
        (*done)({SeatHoldOutcome::Unavailable, {}});
    }
}
}  // namespace ticketing
