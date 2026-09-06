#include "security/PasswordHashExecutor.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <string>

namespace
{
constexpr char kHash[] =
    "$argon2id$v=19$m=65536,t=2,p=1$tUON0+a+tW+XPmzdPL+RoA$"
    "OCRPrfDL//acztJL8FF4AhlFnL7GN03xL4mAsYextRo";

class RecordingObserver final : public ticketing::PasswordHashObserver
{
  public:
    void onSubmission(bool accepted, std::size_t queueDepth) noexcept override
    {
        if (accepted)
            ++acceptedSubmissions;
        else
            ++rejectedSubmissions;
        lastQueueDepth = queueDepth;
    }

    void onExecutionStarted(std::size_t queueDepth,
                            std::size_t activeWorkers,
                            double queueWaitSeconds) noexcept override
    {
        lastQueueDepth = queueDepth;
        lastActiveWorkers = activeWorkers;
        queueWaitObserved = queueWaitSeconds >= 0.0;
    }

    void onExecutionFinished(std::size_t activeWorkers,
                             double executionSeconds) noexcept override
    {
        lastActiveWorkers = activeWorkers;
        executionObserved = executionSeconds > 0.0;
    }

    std::atomic_size_t acceptedSubmissions{0};
    std::atomic_size_t rejectedSubmissions{0};
    std::atomic_size_t lastQueueDepth{0};
    std::atomic_size_t lastActiveWorkers{0};
    std::atomic_bool queueWaitObserved{false};
    std::atomic_bool executionObserved{false};
};

bool rejectionIsObservable()
{
    auto observer = std::make_shared<RecordingObserver>();
    ticketing::PasswordHashExecutor executor{0, 1, observer};
    const auto first = executor.verify("one", kHash, [](bool) {});
    const auto second = executor.verify("two", kHash, [](bool) {});
    return first && !second && observer->acceptedSubmissions == 1 &&
           observer->rejectedSubmissions == 1 && observer->lastQueueDepth == 1;
}

bool executionIsObservable()
{
    auto observer = std::make_shared<RecordingObserver>();
    std::mutex mutex;
    std::condition_variable completed;
    bool done = false;
    bool matched = false;
    {
        ticketing::PasswordHashExecutor executor{1, 2, observer};
        if (!executor.verify("Ticketing123!", kHash, [&](bool result) {
                {
                    std::lock_guard lock{mutex};
                    matched = result;
                    done = true;
                }
                completed.notify_one();
            }))
        {
            return false;
        }
        std::unique_lock lock{mutex};
        if (!completed.wait_for(lock, std::chrono::seconds{10},
                                [&] { return done; }))
        {
            return false;
        }
    }
    return matched && observer->acceptedSubmissions == 1 &&
           observer->rejectedSubmissions == 0 &&
           observer->lastQueueDepth == 0 &&
           observer->lastActiveWorkers == 0 && observer->queueWaitObserved &&
           observer->executionObserved;
}
}  // namespace

int main()
{
    return rejectionIsObservable() && executionIsObservable() ? EXIT_SUCCESS
                                                               : EXIT_FAILURE;
}
