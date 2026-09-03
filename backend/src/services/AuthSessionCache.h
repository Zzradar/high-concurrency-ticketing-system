#pragma once

#include "repositories/UserSessionRepository.h"

#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
enum class SessionCacheOutcome
{
    Hit,
    Miss,
    Unavailable,
};

struct SessionCacheResult
{
    SessionCacheOutcome outcome{SessionCacheOutcome::Unavailable};
    std::optional<AuthSessionRecord> value;
};

class AuthSessionCache
{
  public:
    void get(const std::string &tokenHash,
             std::function<void(SessionCacheResult)> completion) const;
    void put(const std::string &tokenHash,
             const AuthSessionRecord &record) const;
    void remove(const std::string &tokenHash) const;

    static std::string keyFor(const std::string &tokenHash);
};
}  // namespace ticketing
