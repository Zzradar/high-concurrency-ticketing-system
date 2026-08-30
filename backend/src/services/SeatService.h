#pragma once

#include "dto/TicketDtos.h"
#include "repositories/SeatRepository.h"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
class SeatService
{
  public:
    using ErrorCallback = std::function<void()>;
    using SeatsResult = std::optional<std::vector<Seat>>;

    void listSessionSeats(
        const std::string &sessionId,
        std::function<void(SeatsResult)> onSuccess,
        ErrorCallback onError) const;

  private:
    static Seat toDto(SeatRow row);

    SeatRepository repository_;
};
}  // namespace ticketing
