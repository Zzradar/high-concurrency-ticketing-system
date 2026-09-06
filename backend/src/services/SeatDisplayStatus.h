#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace ticketing
{
std::string displaySeatStatus(
    std::string_view formalStatus,
    const std::optional<std::string> &temporaryHoldOwner,
    std::string_view ownCheckoutSessionId);
}  // namespace ticketing
