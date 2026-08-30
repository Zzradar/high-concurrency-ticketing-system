#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
struct EventRow
{
    std::string id;
    std::string name;
    std::string description;
    std::string city;
    std::string venue;
    std::string dateRange;
    std::string status;
    std::string cover;
    std::int64_t sessionCount{};
    std::string category;
};

class EventRepository
{
  public:
    using ErrorCallback = std::function<void()>;

    void listEvents(
        std::function<void(std::vector<EventRow>)> onSuccess,
        ErrorCallback onError) const;

    void findEventById(
        const std::string &eventId,
        std::function<void(std::optional<EventRow>)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
