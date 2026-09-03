#pragma once

#include "security/AuthConfig.h"

#include <string>
#include <string_view>

namespace ticketing
{
class PasswordHasher
{
  public:
    static std::string hash(std::string_view password, const AuthConfig &config);
    static bool verify(std::string_view password, std::string_view encodedHash);
};
}  // namespace ticketing
