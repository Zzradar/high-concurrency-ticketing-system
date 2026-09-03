#include "services/AuthService.h"

#include "security/AuthConfig.h"
#include "security/Crypto.h"
#include "security/PasswordHashExecutor.h"

#include <drogon/utils/Utilities.h>

#include <algorithm>
#include <cctype>
#include <memory>
#include <utility>

namespace
{
constexpr std::string_view kDummyHash =
    "$argon2id$v=19$m=65536,t=2,p=1$tUON0+a+tW+XPmzdPL+RoA$"
    "OCRPrfDL//acztJL8FF4AhlFnL7GN03xL4mAsYextRo";

ticketing::PasswordHashExecutor &passwordExecutor()
{
    static const auto config = ticketing::AuthConfig::load();
    static ticketing::PasswordHashExecutor executor{
        config.passwordHashWorkers, config.passwordHashQueueCapacity};
    return executor;
}

bool validUsername(const std::string &username)
{
    return username.size() >= 3 && username.size() <= 64 &&
           std::all_of(username.begin(), username.end(), [](unsigned char value) {
               return std::islower(value) || std::isdigit(value) || value == '.' ||
                      value == '_' || value == '-';
           });
}
}  // namespace

namespace ticketing
{
std::string AuthService::canonicalUsername(std::string value)
{
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    value = value.substr(first, last - first + 1);
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char ch) { return std::tolower(ch); });
    return value;
}

void AuthService::login(std::string username,
                        std::string password,
                        std::string peerIp,
                        std::function<void(LoginResult)> completion) const
{
    username = canonicalUsername(std::move(username));
    auto done = std::make_shared<decltype(completion)>(std::move(completion));
    if (!validUsername(username) || password.empty() || password.size() > 1024)
    {
        (*done)({LoginOutcome::InvalidArgument});
        return;
    }
    rateLimiter_.check(
        username, peerIp,
        [this, username = std::move(username), password = std::move(password),
         peerIp = std::move(peerIp), done](bool allowed) mutable {
            if (!allowed)
            {
                (*done)({LoginOutcome::TooManyAttempts});
                return;
            }
            userRepository_.findByUsername(
                username,
                [this, username, password = std::move(password), peerIp, done](
                    std::optional<UserRecord> user) mutable {
                    const bool eligible = user && user->status == "ACTIVE" &&
                                          !user->passwordHash.starts_with('!');
                    const std::string encoded = eligible
                                                    ? user->passwordHash
                                                    : std::string{kDummyHash};
                    const bool queued = passwordExecutor().verify(
                        std::move(password), encoded,
                        [this, username, peerIp, done,
                         user = std::move(user), eligible](bool matches) mutable {
                            if (!eligible || !matches || !user)
                            {
                                rateLimiter_.recordFailure(
                                    username, peerIp,
                                    [done] { (*done)({LoginOutcome::InvalidCredentials}); });
                                return;
                            }
                            try
                            {
                                const auto config = AuthConfig::load();
                                auto rawToken = randomHex(32);
                                auto csrfToken = randomHex(32);
                                auto tokenHash = sha256Hex(rawToken);
                                auto sessionId = "AUTH-" + drogon::utils::getUuid();
                                sessionRepository_.create(
                                    sessionId, user->id, tokenHash,
                                    config.idleTimeoutSeconds,
                                    config.absoluteTimeoutSeconds,
                                    [this, username, tokenHash,
                                     rawToken = std::move(rawToken),
                                     csrfToken = std::move(csrfToken), done](
                                        std::optional<AuthSessionRecord> session) mutable {
                                        if (!session)
                                        {
                                            (*done)({LoginOutcome::Unavailable});
                                            return;
                                        }
                                        cache_.put(tokenHash, *session);
                                        rateLimiter_.clearUsername(username);
                                        (*done)({LoginOutcome::Succeeded,
                                                 std::move(session),
                                                 std::move(rawToken),
                                                 std::move(csrfToken)});
                                    },
                                    [done] { (*done)({LoginOutcome::Unavailable}); });
                            }
                            catch (...)
                            {
                                (*done)({LoginOutcome::Unavailable});
                            }
                        });
                    if (!queued) (*done)({LoginOutcome::Busy});
                },
                [done] { (*done)({LoginOutcome::Unavailable}); });
        });
}

void AuthService::logout(std::string sessionId,
                         std::string tokenHash,
                         std::function<void(bool)> completion) const
{
    sessionService_.revoke(std::move(sessionId), std::move(tokenHash),
                           std::move(completion));
}
}  // namespace ticketing
