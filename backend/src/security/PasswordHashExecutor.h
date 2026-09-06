#pragma once

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <mutex>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace ticketing
{
class PasswordHashObserver
{
  public:
    virtual ~PasswordHashObserver() = default;
    virtual void onSubmission(bool accepted,
                              std::size_t queueDepth) noexcept = 0;
    virtual void onExecutionStarted(std::size_t queueDepth,
                                    std::size_t activeWorkers,
                                    double queueWaitSeconds) noexcept = 0;
    virtual void onExecutionFinished(std::size_t activeWorkers,
                                     double executionSeconds) noexcept = 0;
};

class PasswordHashExecutor
{
  public:
    using Completion = std::function<void(bool)>;

    PasswordHashExecutor(
        std::size_t workerCount,
        std::size_t queueCapacity,
        std::shared_ptr<PasswordHashObserver> observer = nullptr);
    ~PasswordHashExecutor();
    PasswordHashExecutor(const PasswordHashExecutor &) = delete;
    PasswordHashExecutor &operator=(const PasswordHashExecutor &) = delete;

    bool verify(std::string password,
                std::string encodedHash,
                Completion completion);

  private:
    struct WorkItem
    {
        std::function<void()> work;
        std::chrono::steady_clock::time_point enqueuedAt;
    };
    void run();

    std::size_t queueCapacity_;
    std::mutex mutex_;
    std::condition_variable available_;
    bool stopping_{false};
    std::deque<WorkItem> queue_;
    std::size_t activeWorkers_{0};
    std::shared_ptr<PasswordHashObserver> observer_;
    std::vector<std::thread> workers_;
};
}  // namespace ticketing
