#pragma once

#include "dto/TicketDtos.h"
#include "repositories/EventRepository.h"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
class EventService
{
  public:
    using ErrorCallback = std::function<void()>;

    void listEvents(
        std::function<void(std::vector<TicketEvent>)> onSuccess,
        ErrorCallback onError) const;

    void getEvent(
        const std::string &eventId,
        std::function<void(std::optional<TicketEvent>)> onSuccess,
        ErrorCallback onError) const;

  private:
    static TicketEvent toDto(EventRow row);

    EventRepository repository_;
};
}  // namespace ticketing
