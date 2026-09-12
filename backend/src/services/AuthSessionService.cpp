#include "admission/AdmissionMetrics.h"
#include "admission/TrafficControl.h"
#include "services/AuthSessionService.h"

#include "security/AuthConfig.h"
#include "security/Crypto.h"

#include <chrono>
#include <mutex>
#include <unordered_map>
#include <vector>
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

void AuthSessionService::authenticateReadOnly(std::string rawToken, Completion completion) const {
    if(rawToken.size()!=64 || rawToken.find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos) {
        completion({AuthenticateOutcome::Unauthenticated,std::nullopt,{}});return;
    }
    const auto tokenHash=sha256Hex(rawToken);
    cache_.get(tokenHash,[this,tokenHash,rawToken,completion=std::move(completion)](SessionCacheResult result) mutable {
        if(result.outcome==SessionCacheOutcome::Hit && result.value) {
            const auto &r=*result.value;const auto now=nowEpoch();const auto config=AuthConfig::load();
            if(r.createdAtEpoch>0 && r.createdAtEpoch<=r.lastSeenAtEpoch && r.lastSeenAtEpoch<=now &&
               now<r.idleExpiresAtEpoch && now<r.absoluteExpiresAtEpoch &&
               now-r.lastSeenAtEpoch<config.idleTimeoutSeconds && now-r.createdAtEpoch<config.absoluteTimeoutSeconds) {
                // Read-only hits do not touch PostgreSQL, refresh the cache TTL or renew the session.
                completion({AuthenticateOutcome::Authenticated,std::move(result.value),tokenHash});return;
            }
        }
        static std::mutex pendingMutex;
        static std::unordered_map<std::string,std::vector<Completion>> pending;
        bool first=false,reject=false;
        {
            std::lock_guard lock(pendingMutex);auto found=pending.find(tokenHash);
            if(found!=pending.end()) {
                if(found->second.size()>=8)reject=true;
                else found->second.push_back(std::move(completion));
            }else if(pending.size()>=64)reject=true;
            else{pending.emplace(tokenHash,std::vector<Completion>{std::move(completion)});first=true;}
        }
        if(reject){completion({AuthenticateOutcome::Unavailable,std::nullopt,tokenHash});return;}
        if(!first)return;
        // The existing strict path remains authoritative on misses, including role/revocation.
        auto permit=admission::TrafficControl::acquire(admission::Resource::PostgresFallback);
        auto completed=[tokenHash,permit](AuthenticateResult authenticated) {
            std::vector<Completion> callbacks;
            {std::lock_guard lock(pendingMutex);callbacks=std::move(pending.at(tokenHash));pending.erase(tokenHash);}
            for(auto &callback:callbacks)callback(authenticated);
        };
        if(!permit){admission::AdmissionMetrics::count("ticketing_admission_auth_fallback_total",{"OVERLOADED"});completed({AuthenticateOutcome::Overloaded,std::nullopt,tokenHash});return;}
        admission::AdmissionMetrics::count("ticketing_admission_auth_fallback_total",{"STARTED"});
        authenticate(rawToken,std::move(completed));
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
        [this, tokenHash, cached, done](std::optional<std::string> role) mutable {
            if (!role)
            {
                cache_.remove(tokenHash);
                (*done)({AuthenticateOutcome::Unauthenticated,
                         std::nullopt, tokenHash});
                return;
            }
            cached->role = std::move(*role);
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
