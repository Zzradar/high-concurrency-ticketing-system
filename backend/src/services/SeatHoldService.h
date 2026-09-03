#pragma once

#include <functional>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
enum class SeatHoldOutcome
{
    Applied,
    Conflict,
    Unavailable,
};

struct SeatHoldReadResult
{
    SeatHoldOutcome outcome{SeatHoldOutcome::Unavailable};
    std::vector<std::optional<std::string>> owners;
};

class SeatHoldService
{
  public:
    using Completion = std::function<void(SeatHoldOutcome)>;
    using ReadCompletion = std::function<void(SeatHoldReadResult)>;

    static void validateConfiguration();

    void prepare(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::vector<std::string> &addedSeatIds,
        const std::vector<std::string> &retainedSeatIds,
        std::int64_t baseRevision,
        std::int64_t targetRevision,
        Completion completion) const;

    void abort(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::vector<std::string> &addedSeatIds,
        std::int64_t targetRevision,
        Completion completion) const;

    void finalize(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::vector<std::string> &removedSeatIds,
        std::int64_t targetRevision,
        Completion completion) const;

    void ensure(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::vector<std::string> &seatIds,
        std::int64_t revision,
        Completion completion) const;

    void release(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::vector<std::string> &seatIds,
        Completion completion) const;

    void readOwners(
        const std::string &sessionId,
        const std::vector<std::string> &seatIds,
        ReadCompletion completion) const;

    static std::string keyFor(
        const std::string &sessionId,
        const std::string &sessionSeatId);

  private:
    static int ttlSeconds();
};
}  // namespace ticketing
