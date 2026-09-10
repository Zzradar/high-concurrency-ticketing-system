#pragma once

#include <atomic>
#include <algorithm>
#include <chrono>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <set>

namespace ticketing
{
enum class ObservationOutcome { Success, Empty, Error, Timeout, Abandoned };

// Framework-independent lifetime tracking. Timestamps never become metric labels.
class ObservationSeries
{
  public:
    using Clock = std::chrono::steady_clock;
    using Sink = std::function<void(double, double, double, double, ObservationOutcome, bool)>;
    explicit ObservationSeries(Sink sink) : sink_(std::move(sink)) {}
    std::size_t begin(Clock::time_point now)
    {
        std::lock_guard lock{mutex_};
        const auto id = ++sequence_;
        pending_.emplace(id, now);
        starts_.insert(now);
        highWater_ = std::max(highWater_, pending_.size());
        publish(now, 0, ObservationOutcome::Success, false);
        return id;
    }
    void finish(std::size_t id, Clock::time_point now, ObservationOutcome outcome) noexcept
    {
        std::lock_guard lock{mutex_};
        const auto item = pending_.find(id);
        if (item == pending_.end()) return;
        const double elapsed = std::chrono::duration<double>(now - item->second).count();
        starts_.erase(starts_.find(item->second));
        pending_.erase(item);
        publish(now, elapsed, outcome, true);
    }
    void sample() noexcept
    {
        std::lock_guard lock{mutex_};
        publish(Clock::now(), 0, ObservationOutcome::Success, false);
    }
  private:
    void publish(Clock::time_point now, double elapsed, ObservationOutcome outcome, bool completed) noexcept
    {
        const double oldest = starts_.empty() ? 0 : std::chrono::duration<double>(now-*starts_.begin()).count();
        try { sink_(pending_.size(), highWater_, oldest, elapsed, outcome, completed); }
        catch (...) { /* Observability must not alter a business callback. */ }
    }
    Sink sink_;
    std::mutex mutex_;
    std::map<std::size_t, Clock::time_point> pending_;
    std::multiset<Clock::time_point> starts_;
    std::size_t sequence_{}, highWater_{};
};

class AsyncObservation final
{
  public:
    explicit AsyncObservation(std::shared_ptr<ObservationSeries> series)
        : series_(std::move(series)), id_(series_->begin(ObservationSeries::Clock::now())) {}
    ~AsyncObservation() { finish(ObservationOutcome::Abandoned); }
    void finish(ObservationOutcome outcome = ObservationOutcome::Success) noexcept
    {
        if (!completed_.exchange(true)) series_->finish(id_, ObservationSeries::Clock::now(), outcome);
    }
    AsyncObservation(const AsyncObservation &) = delete;
    AsyncObservation &operator=(const AsyncObservation &) = delete;
  private:
    std::shared_ptr<ObservationSeries> series_;
    std::size_t id_;
    std::atomic_bool completed_{false};
};
} // namespace ticketing
