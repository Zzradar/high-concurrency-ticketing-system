#include "services/SeatDisplayStatus.h"

#include <cassert>
#include <optional>
#include <string>

int main()
{
    using ticketing::displaySeatStatus;
    const std::optional<std::string> noOwner;
    const std::optional<std::string> otherOwner{"C-OTHER"};
    const std::optional<std::string> ownOwner{"C-OWN"};

    assert(displaySeatStatus("AVAILABLE", noOwner, "") == "AVAILABLE");
    assert(displaySeatStatus("AVAILABLE", otherOwner, "C-OWN") == "HELD");
    assert(displaySeatStatus("AVAILABLE", ownOwner, "C-OWN") == "AVAILABLE");
    assert(displaySeatStatus("HELD", noOwner, "") == "HELD");
    assert(displaySeatStatus("HELD", ownOwner, "C-OWN") == "HELD");
    assert(displaySeatStatus("SOLD", noOwner, "") == "SOLD");
    assert(displaySeatStatus("SOLD", ownOwner, "C-OWN") == "SOLD");
}
