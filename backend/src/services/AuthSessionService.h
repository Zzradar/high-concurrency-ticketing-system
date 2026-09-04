#pragma once

#include "repositories/UserSessionRepository.h"
#include "services/AuthSessionCache.h"

#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
enum class AuthenticateOutcome
{
    Authenticated,
    Unauthenticated,
    Unavailable,
};

struct AuthenticateResult
{
    AuthenticateOutcome outcome{AuthenticateOutcome::Unavailable};
    std::optional<AuthSessionRecord> session;
    std::string tokenHash;
};

class AuthSessionService
{
  public:
    using Completion = std::function<void(AuthenticateResult)>;

    void authenticate(std::string rawToken, Completion completion) const;
    void revoke(std::string sessionId,
                std::string tokenHash,
                std::function<void(bool)> completion) const;

  private:
    void loadFromDatabase(const std::string &tokenHash,
                          Completion completion) const;
    void validateCachedRecord(const std::string &tokenHash,
                              AuthSessionRecord record,
                              Completion completion) const;
    void finishRecord(const std::string &tokenHash,
                      AuthSessionRecord record,
                      Completion completion) const;

    UserSessionRepository repository_;
    AuthSessionCache cache_;
};
}  // namespace ticketing
