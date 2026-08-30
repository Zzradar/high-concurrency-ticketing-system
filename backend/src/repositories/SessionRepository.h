#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace ticketing
{
struct SessionRow
{
    std::string id;
    std::string eventId;
    std::string date;
    std::string time;
    std::string weekday;
    std::string venue;
    std::string gateTime;
    std::string databaseStatus;
    std::int64_t priceFrom{};
    std::int64_t totalCount{};
    std::int64_t availableCount{};
};

class SessionRepository
{
  public:
    using ErrorCallback = std::function<void()>;

    void listByEventId(
        const std::string &eventId,
        std::function<void(std::vector<SessionRow>)> onSuccess,
        ErrorCallback onError) const;

    void eventExists(
        const std::string &eventId,
        std::function<void(bool)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
