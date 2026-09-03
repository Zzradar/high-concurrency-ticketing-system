#pragma once

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace ticketing
{
class PasswordHashExecutor
{
  public:
    using Completion = std::function<void(bool)>;

    PasswordHashExecutor(std::size_t workerCount, std::size_t queueCapacity);
    ~PasswordHashExecutor();
    PasswordHashExecutor(const PasswordHashExecutor &) = delete;
    PasswordHashExecutor &operator=(const PasswordHashExecutor &) = delete;

    bool verify(std::string password,
                std::string encodedHash,
                Completion completion);

  private:
    void run();

    std::size_t queueCapacity_;
    std::mutex mutex_;
    std::condition_variable available_;
    bool stopping_{false};
    std::deque<std::function<void()>> queue_;
    std::vector<std::thread> workers_;
};
}  // namespace ticketing
