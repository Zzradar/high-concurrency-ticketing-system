#pragma once

#include <cstdint>
#include <optional>
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

struct SeatLayoutRow
{
    std::string id;
    std::string label;
    std::string row;
    std::int32_t number{};
    std::string zone;
    std::int64_t price{};
};

struct SeatAvailabilityRow
{
    std::string id;
    std::string status;
};

class SeatRepository
{
  public:
    using ErrorCallback = std::function<void()>;

    void listBySessionId(
        const std::string &sessionId,
        std::function<void(std::vector<SeatRow>)> onSuccess,
        ErrorCallback onError) const;

    void listLayoutBySessionId(
        const std::string &sessionId,
        std::function<void(std::vector<SeatLayoutRow>)> onSuccess,
        ErrorCallback onError) const;

    void listAvailabilityBySessionId(
        const std::string &sessionId,
        std::function<void(std::vector<SeatAvailabilityRow>)> onSuccess,
        ErrorCallback onError) const;

    void publicLayoutIdentity(const std::string &sessionId,
        std::function<void(std::optional<std::string>)> onSuccess,ErrorCallback onError) const;

    void sessionExists(
        const std::string &sessionId,
        std::function<void(bool)> onSuccess,
        ErrorCallback onError) const;
};
}  // namespace ticketing
