#pragma once

#include "dto/TicketDtos.h"

#include <drogon/orm/DbClient.h>

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace ticketing
{
class NotificationRepository
{
  public:
    using TransactionPtr = std::shared_ptr<drogon::orm::Transaction>;
    using ErrorCallback = std::function<void()>;

    void insert(const TransactionPtr &transaction,
                const std::string &id,
                const std::string &userId,
                const std::string &orderId,
                const std::string &type,
                const std::string &title,
                const std::string &message,
                const std::string &dedupeKey,
                std::function<void(std::size_t)> onSuccess,
                ErrorCallback onError) const;
    void findForUser(const drogon::orm::DbClientPtr &client,
                     const std::string &userId,
                     std::function<void(std::vector<UserNotification>)> onSuccess,
                     ErrorCallback onError) const;
    void markReadForUser(const drogon::orm::DbClientPtr &client,
                         const std::string &notificationId,
                         const std::string &userId,
                         std::function<void(std::optional<UserNotification>)> onSuccess,
                         ErrorCallback onError) const;
};
}  // namespace ticketing
