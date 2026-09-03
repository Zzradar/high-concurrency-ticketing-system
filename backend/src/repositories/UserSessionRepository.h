#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
struct AuthSessionRecord
{
    std::string sessionId;
    std::string userId;
    std::string username;
    std::string displayName;
    std::int64_t createdAtEpoch{};
    std::int64_t lastSeenAtEpoch{};
    std::int64_t idleExpiresAtEpoch{};
    std::int64_t absoluteExpiresAtEpoch{};
};

class UserSessionRepository
{
  public:
    using Completion =
        std::function<void(std::optional<AuthSessionRecord>)>;
    using ErrorCallback = std::function<void()>;

    void create(const std::string &sessionId,
                const std::string &userId,
                const std::string &tokenHash,
                std::int64_t idleTimeoutSeconds,
                std::int64_t absoluteTimeoutSeconds,
                Completion onSuccess,
                ErrorCallback onError) const;
    void findActiveByTokenHash(const std::string &tokenHash,
                               Completion onSuccess,
                               ErrorCallback onError) const;
    void touch(const std::string &sessionId,
               std::int64_t idleTimeoutSeconds,
               Completion onSuccess,
               ErrorCallback onError) const;
    void revoke(const std::string &sessionId,
                std::function<void(bool)> onSuccess,
                ErrorCallback onError) const;
};
}  // namespace ticketing
