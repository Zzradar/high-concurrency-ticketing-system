#pragma once

#include <drogon/orm/DbClient.h>

#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
struct UserRecord
{
    std::string id;
    std::string username;
    std::string displayName;
    std::string passwordHash;
    std::string status;
};

class UserRepository
{
  public:
    using ErrorCallback = std::function<void()>;

    void findByUsername(
        const std::string &username,
        std::function<void(std::optional<UserRecord>)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
