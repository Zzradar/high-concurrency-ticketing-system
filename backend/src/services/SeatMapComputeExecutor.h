#pragma once

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

namespace ticketing
{
class SeatMapComputeObserver
{
  public:
    virtual ~SeatMapComputeObserver() = default;
    // Called under the queue mutex: implementations must not block or reenter.
    virtual void submitted(bool accepted, std::size_t depth) noexcept = 0;
    virtual void started(std::size_t depth, std::size_t active, double wait) noexcept = 0;
    virtual void finished(std::size_t active, double elapsed) noexcept = 0;
};

// Dedicated CPU resource, not an I/O loop or an end-to-end request limit.
class SeatMapComputeExecutor final
{
  public:
    using Task = std::function<void()>;
    SeatMapComputeExecutor(std::size_t workers, std::size_t capacity,
                           std::shared_ptr<SeatMapComputeObserver> observer = {});
    ~SeatMapComputeExecutor();
    SeatMapComputeExecutor(const SeatMapComputeExecutor &) = delete;
    SeatMapComputeExecutor &operator=(const SeatMapComputeExecutor &) = delete;

    // No waiting for capacity and no inline work. False means caller must reply.
    bool trySubmit(Task work, Task onError);
    // Application owner calls from a non-worker thread; drains accepted work.
    void shutdown();

  private:
    struct WorkItem
    {
        Task work;
        Task onError;
        std::chrono::steady_clock::time_point enqueued;
    };
    void run();
    const std::size_t capacity_;
    std::shared_ptr<SeatMapComputeObserver> observer_;
    std::mutex mutex_;
    std::mutex shutdownMutex_;
    std::condition_variable ready_;
    std::deque<WorkItem> queue_;
    std::vector<std::thread> workers_;
    std::size_t active_{};
    bool stopping_{};
};
}  // namespace ticketing
