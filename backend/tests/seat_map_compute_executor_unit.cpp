#include "services/SeatMapComputeExecutor.h"

#include <atomic>
#include <algorithm>
#include <future>
#include <iostream>
#include <latch>
#include <stdexcept>
#include <string>

namespace
{
void require(bool value, const char *message)
{
    if (!value) throw std::runtime_error(message);
}
struct Observer final : ticketing::SeatMapComputeObserver
{
    std::size_t accepted{}, rejected{}, depth{}, active{}, peakDepth{}, peakActive{}, completed{};
    bool nonnegative{true};
    void submitted(bool ok, std::size_t size) noexcept override
    {
        ok ? ++accepted : ++rejected;
        depth = size;
        peakDepth = std::max(peakDepth, size);
    }
    void started(std::size_t size, std::size_t running, double wait) noexcept override
    {
        depth = size; active = running;
        peakActive = std::max(peakActive, active);
        nonnegative = nonnegative && wait >= 0;
    }
    void finished(std::size_t running, double elapsed) noexcept override
    {
        active = running; ++completed;
        nonnegative = nonnegative && elapsed >= 0;
    }
};
struct ReleaseOnExit
{
    std::latch &gate;
    ~ReleaseOnExit() { gate.count_down(); }
};

void boundedAndDrain(std::size_t workers)
{
    auto observer = std::make_shared<Observer>();
    ticketing::SeatMapComputeExecutor executor(workers, 2, observer);
    std::latch release(1);
    std::atomic_int ran{}, errors{};
    const auto caller = std::this_thread::get_id();
    std::atomic_bool offCaller{true}, rejectedRan{false};
    std::weak_ptr<std::vector<std::string>> lifetime;
    {
        ReleaseOnExit guard{release};
        for (std::size_t i = 0; i < workers; ++i)
        {
            auto entered = std::make_shared<std::promise<void>>();
            auto running = entered->get_future();
            require(executor.trySubmit([&, entered] {
                if (std::this_thread::get_id() == caller) offCaller = false;
                entered->set_value(); release.wait(); ++ran;
            }, [&] { ++errors; }), "worker submission rejected");
            running.get();
        }
        auto payload = std::make_shared<std::vector<std::string>>(5000, "owned-seat");
        lifetime = payload;
        require(executor.trySubmit([owned = std::move(payload), &ran] {
            require(owned->size() == 5000, "owned payload lost"); ++ran;
        }, [&] { ++errors; }), "queue slot 1 rejected");
        require(executor.trySubmit([] { throw std::runtime_error("injected"); },
                                   [&] { ++errors; throw std::runtime_error("completion injected"); }),
                "queue slot 2 rejected");
        require(!executor.trySubmit([&] { rejectedRan = true; }, [&] { ++errors; }),
                "full queue accepted work");
        require(!rejectedRan && ran == 0, "full queue ran inline or workers did not wait");
    }
    executor.shutdown();
    executor.shutdown();
    require(!executor.trySubmit([&] { rejectedRan = true; }, [&] { ++errors; }),
            "stopped executor accepted work");
    require(offCaller && !rejectedRan, "work executed on submitting thread");
    require(ran == static_cast<int>(workers + 1) && errors == 1, "completion count mismatch");
    require(lifetime.expired(), "queued payload retained after drain");
    require(observer->accepted == workers + 2 && observer->rejected == 2, "submission metrics mismatch");
    require(observer->depth == 0 && observer->active == 0 && observer->peakDepth == 2 &&
            observer->peakActive == workers && observer->completed == workers + 2 && observer->nonnegative,
            "queue metrics mismatch");
}

void errorDoesNotKillWorker()
{
    ticketing::SeatMapComputeExecutor executor(1, 2);
    std::promise<void> failed, next;
    require(executor.trySubmit([] { throw 1; }, [&] { failed.set_value(); }), "submit failed");
    failed.get_future().get();
    require(executor.trySubmit([&] { next.set_value(); }, [] {}), "worker not reusable");
    next.get_future().get();
    executor.shutdown();
}
}

int main()
{
    try
    {
        for (auto [workers, queue] : {std::pair{0u, 16u}, {5u, 16u}, {2u, 0u}, {2u, 65u}})
        {
            bool rejected = false;
            try { ticketing::SeatMapComputeExecutor executor(workers, queue); }
            catch (const std::invalid_argument &) { rejected = true; }
            require(rejected, "invalid resource bounds accepted");
        }
        boundedAndDrain(2);
        boundedAndDrain(4);
        errorDoesNotKillWorker();
        std::cout << "PASS: 2/4 workers, full queue, off-thread execution, ownership, exceptions, drain and shutdown\n";
        return 0;
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
