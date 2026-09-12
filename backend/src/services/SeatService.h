#pragma once

#include "dto/TicketDtos.h"
#include "repositories/SeatRepository.h"
#include "services/SeatHoldService.h"
#include "services/SeatMapComputeExecutor.h"

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
    struct LayoutSnapshot { std::string etag; std::vector<SeatLayout> seats; };
    using LayoutResult = std::optional<LayoutSnapshot>;
    using AvailabilityResult = std::optional<std::vector<SeatAvailability>>;

    // Configure once before app.run(); main owns shutdown, callbacks share ownership.
    static void configureComputeExecutor(std::shared_ptr<SeatMapComputeExecutor> executor);

    void listSessionSeats(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        std::function<void(SeatsResult)> onSuccess,
        ErrorCallback onError,
        ErrorCallback onBusy) const;

    void listSeatLayout(
        const std::string &sessionId,
        std::function<void(LayoutResult)> onSuccess,
        ErrorCallback onError,
        ErrorCallback onBusy) const;

    void listSeatAvailability(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        std::function<void(AvailabilityResult)> onSuccess,
        ErrorCallback onError,
        ErrorCallback onBusy) const;

  private:
    static Seat toDto(SeatRow row);
    static SeatLayout toLayoutDto(SeatLayoutRow row);

    SeatRepository repository_;
    SeatHoldService seatHoldService_;
};
}  // namespace ticketing
