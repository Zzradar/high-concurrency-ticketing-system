#pragma once

#include "repositories/UserRepository.h"
#include "repositories/UserSessionRepository.h"
#include "services/AuthSessionCache.h"
#include "services/AuthSessionService.h"
#include "services/LoginRateLimiter.h"

#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
enum class LoginOutcome
{
    Succeeded,
    InvalidArgument,
    InvalidCredentials,
    TooManyAttempts,
    Busy,
    Unavailable,
};

struct LoginResult
{
    LoginOutcome outcome{LoginOutcome::Unavailable};
    std::optional<AuthSessionRecord> session;
    std::string rawToken;
    std::string csrfToken;
};

class AuthService
{
  public:
    void login(std::string username,
               std::string password,
               std::string peerIp,
               std::function<void(LoginResult)> completion) const;
    void logout(std::string sessionId,
                std::string tokenHash,
                std::function<void(bool)> completion) const;

    static std::string canonicalUsername(std::string value);

  private:
    UserRepository userRepository_;
    UserSessionRepository sessionRepository_;
    AuthSessionCache cache_;
    AuthSessionService sessionService_;
    LoginRateLimiter rateLimiter_;
};
}  // namespace ticketing
