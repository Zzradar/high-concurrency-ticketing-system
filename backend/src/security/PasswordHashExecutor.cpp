#include "security/PasswordHashExecutor.h"

#include "security/PasswordHasher.h"

#include <utility>

namespace ticketing
{
PasswordHashExecutor::PasswordHashExecutor(std::size_t workerCount,
                                           std::size_t queueCapacity)
    : queueCapacity_(queueCapacity)
{
    workers_.reserve(workerCount);
    for (std::size_t index = 0; index < workerCount; ++index)
    {
        workers_.emplace_back([this] { run(); });
    }
}

PasswordHashExecutor::~PasswordHashExecutor()
{
    {
        std::lock_guard lock{mutex_};
        stopping_ = true;
    }
    available_.notify_all();
    for (auto &worker : workers_) worker.join();
}

bool PasswordHashExecutor::verify(std::string password,
                                  std::string encodedHash,
                                  Completion completion)
{
    std::lock_guard lock{mutex_};
    if (stopping_ || queue_.size() >= queueCapacity_) return false;
    queue_.emplace_back(
        [password = std::move(password), encodedHash = std::move(encodedHash),
         completion = std::move(completion)] {
            completion(PasswordHasher::verify(password, encodedHash));
        });
    available_.notify_one();
    return true;
}

void PasswordHashExecutor::run()
{
    for (;;)
    {
        std::function<void()> work;
        {
            std::unique_lock lock{mutex_};
            available_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
            if (stopping_ && queue_.empty()) return;
            work = std::move(queue_.front());
            queue_.pop_front();
        }
        work();
    }
}
}  // namespace ticketing
