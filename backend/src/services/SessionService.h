#pragma once

#include "dto/TicketDtos.h"
#include "repositories/SessionRepository.h"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
class SessionService
{
  public:
    using ErrorCallback = std::function<void()>;
    using SessionsResult = std::optional<std::vector<TicketSession>>;

    void listEventSessions(
        const std::string &eventId,
        std::function<void(SessionsResult)> onSuccess,
        ErrorCallback onError) const;

  private:
    static TicketSession toDto(SessionRow row);

    SessionRepository repository_;
};
}  // namespace ticketing
