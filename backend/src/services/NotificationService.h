#pragma once

#include "dto/TicketDtos.h"
#include "repositories/NotificationRepository.h"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
enum class NotificationOutcome { Found, InvalidArgument, NotFound, InternalError };

struct NotificationListResult
{
    NotificationOutcome outcome{NotificationOutcome::InternalError};
    std::vector<UserNotification> values;
};

struct NotificationResult
{
    NotificationOutcome outcome{NotificationOutcome::InternalError};
    std::optional<UserNotification> value;
};

class NotificationService
{
  public:
    void list(std::string userId,
              std::function<void(NotificationListResult)> completion) const;
    void markRead(std::string notificationId,
                  std::string userId,
                  std::function<void(NotificationResult)> completion) const;

  private:
    NotificationRepository repository_;
};
}  // namespace ticketing
