#pragma once

#include "services/NotificationService.h"

#include <drogon/HttpController.h>

class NotificationController final
    : public drogon::HttpController<NotificationController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(NotificationController::list, "/notifications", drogon::Get);
    ADD_METHOD_TO(NotificationController::markRead,
                  "/notifications/{notificationId}/read",
                  drogon::Post);
    METHOD_LIST_END

    void list(const drogon::HttpRequestPtr &request,
              std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
    void markRead(const drogon::HttpRequestPtr &request,
                  std::function<void(const drogon::HttpResponsePtr &)> &&callback,
                  std::string notificationId) const;

  private:
    ticketing::NotificationService service_;
};
