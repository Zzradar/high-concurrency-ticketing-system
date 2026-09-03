#pragma once

#include <functional>
#include <string>

namespace ticketing
{
class LoginRateLimiter
{
  public:
    void check(const std::string &username,
               const std::string &peerIp,
               std::function<void(bool)> completion) const;
    void recordFailure(const std::string &username,
                       const std::string &peerIp,
                       std::function<void()> completion) const;
    void clearUsername(const std::string &username) const;

    static std::string usernameKey(const std::string &username);
    static std::string ipKey(const std::string &peerIp);
};
}  // namespace ticketing
