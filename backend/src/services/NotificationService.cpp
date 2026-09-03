#include "services/NotificationService.h"

#include <drogon/drogon.h>

#include <memory>
#include <utility>

namespace ticketing
{
void NotificationService::list(
    std::string userId,
    std::function<void(NotificationListResult)> completion) const
{
    if (userId.empty())
    {
        completion({NotificationOutcome::InvalidArgument, {}});
        return;
    }
    auto completionPtr = std::make_shared<std::function<void(NotificationListResult)>>(std::move(completion));
    repository_.findForUser(
        drogon::app().getDbClient("default"), userId,
        [completionPtr](std::vector<UserNotification> values) {
            (*completionPtr)({NotificationOutcome::Found, std::move(values)});
        },
        [completionPtr] { (*completionPtr)({NotificationOutcome::InternalError, {}}); });
}

void NotificationService::markRead(
    std::string notificationId,
    std::string userId,
    std::function<void(NotificationResult)> completion) const
{
    if (notificationId.empty() || userId.empty())
    {
        completion({NotificationOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto completionPtr = std::make_shared<std::function<void(NotificationResult)>>(std::move(completion));
    repository_.markReadForUser(
        drogon::app().getDbClient("default"), notificationId, userId,
        [completionPtr](std::optional<UserNotification> value) {
            (*completionPtr)({value ? NotificationOutcome::Found
                                    : NotificationOutcome::NotFound,
                              std::move(value)});
        },
        [completionPtr] { (*completionPtr)({NotificationOutcome::InternalError, std::nullopt}); });
}
}  // namespace ticketing
