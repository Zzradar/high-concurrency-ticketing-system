#include "security/PasswordHashExecutor.h"

#include "security/PasswordHasher.h"

#include <chrono>
#include <utility>

namespace ticketing
{
PasswordHashExecutor::PasswordHashExecutor(std::size_t workerCount,
                                           std::size_t queueCapacity,
                                           std::shared_ptr<PasswordHashObserver> observer)
    : queueCapacity_(queueCapacity), observer_(std::move(observer))
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
    std::size_t queueDepth{};
    bool accepted = false;
    {
        std::lock_guard lock{mutex_};
        if (stopping_ || queue_.size() >= queueCapacity_)
        {
            queueDepth = queue_.size();
        }
        else
        {
            queue_.push_back({
                [password = std::move(password),
                 encodedHash = std::move(encodedHash),
                 completion = std::move(completion)] {
                    completion(PasswordHasher::verify(password, encodedHash));
                },
                std::chrono::steady_clock::now(),
            });
            queueDepth = queue_.size();
            accepted = true;
        }
    }
    if (observer_) observer_->onSubmission(accepted, queueDepth);
    if (!accepted) return false;
    available_.notify_one();
    return true;
}

void PasswordHashExecutor::run()
{
    for (;;)
    {
        WorkItem item;
        std::size_t queueDepth{};
        std::size_t activeWorkers{};
        {
            std::unique_lock lock{mutex_};
            available_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
            if (stopping_ && queue_.empty()) return;
            item = std::move(queue_.front());
            queue_.pop_front();
            queueDepth = queue_.size();
            activeWorkers = ++activeWorkers_;
        }
        const auto startedAt = std::chrono::steady_clock::now();
        if (observer_)
        {
            observer_->onExecutionStarted(
                queueDepth,
                activeWorkers,
                std::chrono::duration<double>(startedAt - item.enqueuedAt).count());
        }
        item.work();
        const auto executionSeconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                          startedAt)
                .count();
        {
            std::lock_guard lock{mutex_};
            activeWorkers = --activeWorkers_;
        }
        if (observer_)
        {
            observer_->onExecutionFinished(activeWorkers, executionSeconds);
        }
    }
}
}  // namespace ticketing
