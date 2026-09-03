#include "repositories/NotificationRepository.h"

#include <drogon/drogon.h>

#include <optional>
#include <utility>

namespace ticketing
{
namespace
{
void logDatabaseError(const char *operation,
                      const drogon::orm::DrogonDbException &error)
{
    LOG_ERROR << operation << ": " << error.base().what();
}

UserNotification mapNotification(const drogon::orm::Row &row)
{
    return UserNotification{
        .id = row["id"].as<std::string>(),
        .orderId = row["order_id"].as<std::string>(),
        .type = row["type"].as<std::string>(),
        .title = row["title"].as<std::string>(),
        .message = row["message"].as<std::string>(),
        .createdAt = row["created_at"].as<std::string>(),
        .readAt = row["read_at"].isNull()
                      ? std::nullopt
                      : std::optional<std::string>{row["read_at"].as<std::string>()},
    };
}

constexpr const char *kNotificationColumns = R"SQL(
    id, order_id, type, title, message,
    TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_at,
    CASE WHEN read_at IS NULL THEN NULL ELSE TO_CHAR(read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') END AS read_at
)SQL";
}  // namespace

void NotificationRepository::insert(
    const TransactionPtr &transaction,
    const std::string &id,
    const std::string &userId,
    const std::string &orderId,
    const std::string &type,
    const std::string &title,
    const std::string &message,
    const std::string &dedupeKey,
    std::function<void(std::size_t)> onSuccess,
    ErrorCallback onError) const
{
    transaction->execSqlAsync(
        "INSERT INTO user_notifications (id, user_id, order_id, type, title, message, dedupe_key) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (dedupe_key) DO NOTHING RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) { onSuccess(rows.size()); },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to insert notification", error); onError();
        }, id, userId, orderId, type, title, message, dedupeKey);
}

void NotificationRepository::findForUser(
    const drogon::orm::DbClientPtr &client,
    const std::string &userId,
    std::function<void(std::vector<UserNotification>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "SELECT " + std::string{kNotificationColumns} +
        " FROM user_notifications WHERE user_id = $1 ORDER BY created_at DESC, id DESC";
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            std::vector<UserNotification> values;
            values.reserve(rows.size());
            for (const auto &row : rows) values.push_back(mapNotification(row));
            onSuccess(std::move(values));
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to list notifications", error); onError();
        }, userId);
}

void NotificationRepository::markReadForUser(
    const drogon::orm::DbClientPtr &client,
    const std::string &notificationId,
    const std::string &userId,
    std::function<void(std::optional<UserNotification>)> onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = "UPDATE user_notifications SET read_at = COALESCE(read_at, clock_timestamp()) "
        "WHERE id = $1 AND user_id = $2 RETURNING " + std::string{kNotificationColumns};
    client->execSqlAsync(
        sql,
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(rows.empty() ? std::nullopt
                                   : std::optional<UserNotification>{mapNotification(rows.front())});
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            logDatabaseError("Failed to mark notification read", error); onError();
        }, notificationId, userId);
}
}  // namespace ticketing
