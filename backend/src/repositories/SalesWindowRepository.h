#pragma once
#include "common/SalesWindow.h"
#include <drogon/orm/DbClient.h>
#include <cstdint>
#include <functional>
#include <optional>
namespace ticketing
{
struct SessionSalesGate
{
    std::string eventId, eventStatus, sessionStatus;
    SalesWindowState state{SalesWindowState::Ended};
    std::int64_t remainingMilliseconds{};
    bool staticallyAvailable() const {return eventStatus=="ON_SALE" && sessionStatus=="ON_SALE";}
};
class SalesWindowRepository
{
  public:
    void readSessionGate(const std::shared_ptr<drogon::orm::Transaction> &transaction,
                         const std::string &sessionId,
                         std::function<void(std::optional<SessionSalesGate>)> onSuccess,
                         std::function<void()> onError) const;
};
}
