#include "services/AuthSessionService.h"

#include "security/AuthConfig.h"
#include "security/Crypto.h"

#include <chrono>
#include <memory>
#include <utility>

namespace
{
std::int64_t nowEpoch()
{
    return std::chrono::duration_cast<std::chrono::seconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}
}  // namespace

namespace ticketing
{
void AuthSessionService::authenticate(std::string rawToken,
                                      Completion completion) const
{
    if (rawToken.size() != 64)
    {
        completion({AuthenticateOutcome::Unauthenticated, std::nullopt, {}});
        return;
    }
    std::string tokenHash;
    try
    {
        tokenHash = sha256Hex(rawToken);
    }
    catch (...)
    {
        completion({AuthenticateOutcome::Unavailable, std::nullopt, {}});
        return;
    }
    cache_.get(
        tokenHash,
        [this, tokenHash,
         completion = std::move(completion)](SessionCacheResult result) mutable {
            if (result.outcome == SessionCacheOutcome::Hit && result.value)
            {
                validateCachedRecord(tokenHash, std::move(*result.value),
                                     std::move(completion));
                return;
            }
            loadFromDatabase(tokenHash, std::move(completion));
        });
}

void AuthSessionService::validateCachedRecord(
    const std::string &tokenHash,
    AuthSessionRecord record,
    Completion completion) const
{
    auto done = std::make_shared<Completion>(std::move(completion));
    auto cached = std::make_shared<AuthSessionRecord>(std::move(record));
    repository_.isActive(
        cached->sessionId, tokenHash,
        [this, tokenHash, cached, done](bool active) mutable {
            if (!active)
            {
                cache_.remove(tokenHash);
                (*done)({AuthenticateOutcome::Unauthenticated,
                         std::nullopt, tokenHash});
                return;
            }
            finishRecord(tokenHash, std::move(*cached), std::move(*done));
        },
        [tokenHash, done]() mutable {
            (*done)({AuthenticateOutcome::Unavailable, std::nullopt,
                     tokenHash});
        });
}

void AuthSessionService::loadFromDatabase(const std::string &tokenHash,
                                          Completion completion) const
{
    auto done = std::make_shared<Completion>(std::move(completion));
    repository_.findActiveByTokenHash(
        tokenHash,
        [this, tokenHash, done](std::optional<AuthSessionRecord> record) mutable {
            if (!record)
            {
                (*done)({AuthenticateOutcome::Unauthenticated,
                         std::nullopt, tokenHash});
                return;
            }
            finishRecord(tokenHash, std::move(*record), std::move(*done));
        },
        [tokenHash, done]() mutable {
            (*done)({AuthenticateOutcome::Unavailable, std::nullopt,
                     tokenHash});
        });
}

void AuthSessionService::finishRecord(const std::string &tokenHash,
                                      AuthSessionRecord record,
                                      Completion completion) const
{
    const auto config = AuthConfig::load();
    if (nowEpoch() - record.lastSeenAtEpoch <
        config.lastSeenWriteIntervalSeconds)
    {
        cache_.put(tokenHash, record);
        completion({AuthenticateOutcome::Authenticated, std::move(record),
                    tokenHash});
        return;
    }
    auto done = std::make_shared<Completion>(std::move(completion));
    repository_.touch(
        record.sessionId, config.idleTimeoutSeconds,
        [this, tokenHash, done](std::optional<AuthSessionRecord> touched) mutable {
            if (!touched)
            {
                (*done)({AuthenticateOutcome::Unauthenticated,
                         std::nullopt, tokenHash});
                return;
            }
            cache_.put(tokenHash, *touched);
            (*done)({AuthenticateOutcome::Authenticated,
                     std::move(touched), tokenHash});
        },
        [tokenHash, done]() mutable {
            (*done)({AuthenticateOutcome::Unavailable, std::nullopt,
                     tokenHash});
        });
}

void AuthSessionService::revoke(
    std::string sessionId,
    std::string tokenHash,
    std::function<void(bool)> completion) const
{
    auto done = std::make_shared<std::function<void(bool)>>(std::move(completion));
    repository_.revoke(
        sessionId,
        [this, tokenHash = std::move(tokenHash), done](bool found) mutable {
            cache_.remove(tokenHash);
            (*done)(found);
        },
        [done]() mutable { (*done)(false); });
}
}  // namespace ticketing
