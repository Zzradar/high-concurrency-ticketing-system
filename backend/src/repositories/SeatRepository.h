#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace ticketing
{
struct SeatRow
{
    std::string id;
    std::string sessionId;
    std::string label;
    std::string row;
    std::int32_t number{};
    std::string status;
    std::string zone;
    std::int64_t price{};
};

class SeatRepository
{
  public:
    using ErrorCallback = std::function<void()>;

    void listBySessionId(
        const std::string &sessionId,
        std::function<void(std::vector<SeatRow>)> onSuccess,
        ErrorCallback onError) const;

    void sessionExists(
        const std::string &sessionId,
        std::function<void(bool)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
