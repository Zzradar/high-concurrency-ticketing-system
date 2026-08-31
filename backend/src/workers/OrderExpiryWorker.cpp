#include "workers/OrderExpiryWorker.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
OrderExpiryWorker::OrderExpiryWorker(std::size_t batchSize,
                                     double intervalSeconds)
    : batchSize_(batchSize), intervalSeconds_(intervalSeconds)
{
}

void OrderExpiryWorker::start()
{
    if (started_)
    {
        return;
    }
    started_ = true;
    runCurrentRound();
}

void OrderExpiryWorker::runCurrentRound()
{
    auto weakSelf = weak_from_this();
    service_.runOnce(
        batchSize_,
        [weakSelf](OrderExpiryRunSummary summary) {
            auto self = weakSelf.lock();
            if (!self)
            {
                return;
            }

            if (summary.failed > 0)
            {
                LOG_ERROR << "Order expiry round completed with failures: "
                          << "scanned=" << summary.scanned
                          << ", expired=" << summary.expired
                          << ", skipped=" << summary.skipped
                          << ", failed=" << summary.failed;
            }
            else if (summary.expired > 0)
            {
                LOG_INFO << "Order expiry round completed: "
                         << "scanned=" << summary.scanned
                         << ", expired=" << summary.expired
                         << ", skipped=" << summary.skipped;
            }

            self->scheduleNextRound();
        });
}

void OrderExpiryWorker::scheduleNextRound()
{
    auto weakSelf = weak_from_this();
    drogon::app().getLoop()->runAfter(intervalSeconds_, [weakSelf] {
        if (auto self = weakSelf.lock())
        {
            self->runCurrentRound();
        }
    });
}
}  // namespace ticketing
