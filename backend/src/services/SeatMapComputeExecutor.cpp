#include "services/SeatMapComputeExecutor.h"

#include <stdexcept>
#include <utility>

namespace ticketing
{
SeatMapComputeExecutor::SeatMapComputeExecutor(
    std::size_t workers, std::size_t capacity,
    std::shared_ptr<SeatMapComputeObserver> observer)
    : capacity_(capacity), observer_(std::move(observer))
{
    if (workers == 0 || workers > 4 || capacity == 0 || capacity > 64)
        throw std::invalid_argument("seat map compute requires 1..4 workers and 1..64 queue slots");
    workers_.reserve(workers);
    try
    {
        for (std::size_t index = 0; index < workers; ++index)
            workers_.emplace_back([this] { run(); });
    }
    catch (...)
    {
        shutdown();
        throw;
    }
}

SeatMapComputeExecutor::~SeatMapComputeExecutor()
{
    shutdown();
}

bool SeatMapComputeExecutor::trySubmit(Task work, Task onError)
{
    if (!work || !onError)
        throw std::invalid_argument("seat map task requires work and error completion");
    {
        std::lock_guard lock{mutex_};
        if (stopping_ || queue_.size() >= capacity_)
        {
            if (observer_) observer_->submitted(false, queue_.size());
            return false;
        }
        queue_.push_back({std::move(work), std::move(onError),
                          std::chrono::steady_clock::now()});
        if (observer_) observer_->submitted(true, queue_.size());
    }
    ready_.notify_one();
    return true;
}

void SeatMapComputeExecutor::shutdown()
{
    std::lock_guard shutdownLock{shutdownMutex_};
    {
        std::lock_guard lock{mutex_};
        stopping_ = true;
    }
    ready_.notify_all();
    for (auto &worker : workers_)
        if (worker.joinable()) worker.join();
}

void SeatMapComputeExecutor::run()
{
    for (;;)
    {
        WorkItem item;
        std::chrono::steady_clock::time_point started;
        {
            std::unique_lock lock{mutex_};
            ready_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
            if (queue_.empty()) return;
            item = std::move(queue_.front());
            queue_.pop_front();
            ++active_;
            started = std::chrono::steady_clock::now();
            if (observer_) observer_->started(queue_.size(), active_,
                std::chrono::duration<double>(started - item.enqueued).count());
        }
        try { item.work(); }
        catch (...)
        {
            // Keep the worker alive even if a disconnected request's error
            // completion itself throws. Never retry the expensive task inline.
            try { item.onError(); } catch (...) {}
        }
        // Destroy captured DTOs/owners on this worker, outside the queue lock.
        item.work = {};
        item.onError = {};
        {
            std::lock_guard lock{mutex_};
            --active_;
            if (observer_) observer_->finished(active_,
                std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - started).count());
        }
    }
}
}  // namespace ticketing
