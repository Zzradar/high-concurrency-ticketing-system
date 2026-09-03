#include "repositories/UserSessionRepository.h"

#include <drogon/drogon.h>

#include <utility>

namespace
{
ticketing::AuthSessionRecord mapSession(const drogon::orm::Row &row)
{
    return {
        .sessionId = row["session_id"].as<std::string>(),
        .userId = row["user_id"].as<std::string>(),
        .username = row["username"].as<std::string>(),
        .displayName = row["display_name"].as<std::string>(),
        .createdAtEpoch = row["created_at_epoch"].as<std::int64_t>(),
        .lastSeenAtEpoch = row["last_seen_at_epoch"].as<std::int64_t>(),
        .idleExpiresAtEpoch = row["idle_expires_at_epoch"].as<std::int64_t>(),
        .absoluteExpiresAtEpoch = row["absolute_expires_at_epoch"].as<std::int64_t>(),
    };
}

auto sessionSuccess(ticketing::UserSessionRepository::Completion callback)
{
    return [callback = std::move(callback)](const drogon::orm::Result &rows) {
        callback(rows.empty()
                     ? std::nullopt
                     : std::optional<ticketing::AuthSessionRecord>{
                           mapSession(rows.front())});
    };
}

auto sessionError(const char *operation,
                  ticketing::UserSessionRepository::ErrorCallback callback)
{
    return [operation, callback = std::move(callback)](
               const drogon::orm::DrogonDbException &error) {
        LOG_ERROR << operation << ": " << error.base().what();
        callback();
    };
}

constexpr const char *kReturningSession = R"SQL(
    RETURNING
        user_sessions.id AS session_id,
        user_sessions.user_id,
        (SELECT username FROM app_users WHERE id = user_sessions.user_id) AS username,
        (SELECT display_name FROM app_users WHERE id = user_sessions.user_id) AS display_name,
        EXTRACT(EPOCH FROM created_at)::bigint AS created_at_epoch,
        EXTRACT(EPOCH FROM last_seen_at)::bigint AS last_seen_at_epoch,
        EXTRACT(EPOCH FROM idle_expires_at)::bigint AS idle_expires_at_epoch,
        EXTRACT(EPOCH FROM absolute_expires_at)::bigint AS absolute_expires_at_epoch
)SQL";
}  // namespace

namespace ticketing
{
void UserSessionRepository::create(
    const std::string &sessionId,
    const std::string &userId,
    const std::string &tokenHash,
    std::int64_t idleTimeoutSeconds,
    std::int64_t absoluteTimeoutSeconds,
    Completion onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = std::string{R"SQL(
        INSERT INTO user_sessions (
            id, user_id, token_hash, created_at, last_seen_at,
            idle_expires_at, absolute_expires_at
        ) VALUES (
            $1, $2, $3, clock_timestamp(), clock_timestamp(),
            clock_timestamp() + make_interval(secs => $4),
            clock_timestamp() + make_interval(secs => $5)
        )
    )SQL"} + kReturningSession;
    drogon::app().getDbClient()->execSqlAsync(
        sql, sessionSuccess(std::move(onSuccess)),
        sessionError("Failed to create user session", std::move(onError)),
        sessionId, userId, tokenHash, idleTimeoutSeconds,
        absoluteTimeoutSeconds);
}

void UserSessionRepository::findActiveByTokenHash(
    const std::string &tokenHash,
    Completion onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            auth.id AS session_id, auth.user_id, app_user.username,
            app_user.display_name,
            EXTRACT(EPOCH FROM auth.created_at)::bigint AS created_at_epoch,
            EXTRACT(EPOCH FROM auth.last_seen_at)::bigint AS last_seen_at_epoch,
            EXTRACT(EPOCH FROM auth.idle_expires_at)::bigint AS idle_expires_at_epoch,
            EXTRACT(EPOCH FROM auth.absolute_expires_at)::bigint AS absolute_expires_at_epoch
        FROM user_sessions AS auth
        JOIN app_users AS app_user ON app_user.id = auth.user_id
        WHERE auth.token_hash = $1
          AND auth.revoked_at IS NULL
          AND auth.idle_expires_at > clock_timestamp()
          AND auth.absolute_expires_at > clock_timestamp()
          AND app_user.status = 'ACTIVE'
    )SQL";
    drogon::app().getDbClient()->execSqlAsync(
        sql, sessionSuccess(std::move(onSuccess)),
        sessionError("Failed to authenticate user session", std::move(onError)),
        tokenHash);
}

void UserSessionRepository::touch(
    const std::string &sessionId,
    std::int64_t idleTimeoutSeconds,
    Completion onSuccess,
    ErrorCallback onError) const
{
    const std::string sql = std::string{R"SQL(
        UPDATE user_sessions
        SET last_seen_at = clock_timestamp(),
            idle_expires_at = LEAST(
                clock_timestamp() + make_interval(secs => $2),
                absolute_expires_at
            )
        WHERE id = $1
          AND revoked_at IS NULL
          AND idle_expires_at > clock_timestamp()
          AND absolute_expires_at > clock_timestamp()
    )SQL"} + kReturningSession;
    drogon::app().getDbClient()->execSqlAsync(
        sql, sessionSuccess(std::move(onSuccess)),
        sessionError("Failed to touch user session", std::move(onError)),
        sessionId, idleTimeoutSeconds);
}

void UserSessionRepository::revoke(
    const std::string &sessionId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    drogon::app().getDbClient()->execSqlAsync(
        "UPDATE user_sessions SET revoked_at = COALESCE(revoked_at, clock_timestamp()) "
        "WHERE id = $1 RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(!rows.empty());
        },
        sessionError("Failed to revoke user session", std::move(onError)),
        sessionId);
}
}  // namespace ticketing
