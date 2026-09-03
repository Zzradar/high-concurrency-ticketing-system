#include "repositories/UserRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
void UserRepository::findByUsername(
    const std::string &username,
    std::function<void(std::optional<UserRecord>)> onSuccess,
    ErrorCallback onError) const
{
    drogon::app().getDbClient()->execSqlAsync(
        "SELECT id, username, display_name, password_hash, status "
        "FROM app_users WHERE username = $1",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            if (rows.empty())
            {
                onSuccess(std::nullopt);
                return;
            }
            const auto &row = rows.front();
            onSuccess(UserRecord{
                .id = row["id"].as<std::string>(),
                .username = row["username"].as<std::string>(),
                .displayName = row["display_name"].as<std::string>(),
                .passwordHash = row["password_hash"].as<std::string>(),
                .status = row["status"].as<std::string>(),
            });
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to find authentication user: "
                      << error.base().what();
            onError();
        },
        username);
}
}  // namespace ticketing
