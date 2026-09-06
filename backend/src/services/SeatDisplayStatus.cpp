#include "services/SeatDisplayStatus.h"

namespace ticketing
{
std::string displaySeatStatus(
    std::string_view formalStatus,
    const std::optional<std::string> &temporaryHoldOwner,
    std::string_view ownCheckoutSessionId)
{
    if (formalStatus != "AVAILABLE")
    {
        return std::string{formalStatus};
    }
    if (temporaryHoldOwner &&
        (ownCheckoutSessionId.empty() ||
         *temporaryHoldOwner != ownCheckoutSessionId))
    {
        return "HELD";
    }
    return "AVAILABLE";
}
}  // namespace ticketing
