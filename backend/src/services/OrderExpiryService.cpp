#include "services/OrderExpiryService.h"

#include <drogon/drogon.h>

#include <utility>
#include <vector>

namespace ticketing
{
struct OrderExpiryService::BatchState
{
    std::vector<std::string> orderIds;
    std::size_t nextIndex{};
    OrderExpiryRunSummary summary;
    Completion completion;
};

void OrderExpiryService::runOnce(std::size_t batchSize,
                                 Completion completion) const
{
    auto state = std::make_shared<BatchState>();
    state->completion = std::move(completion);
    auto client = drogon::app().getDbClient("default");
    repository_.findExpiredCandidateIds(
        client,
        batchSize,
        [this, state](std::vector<std::string> orderIds) {
            state->summary.scanned = orderIds.size();
            state->orderIds = std::move(orderIds);
            processNext(state);
        },
        [state] {
            state->summary.failed = 1;
            auto completion = std::move(state->completion);
            completion(state->summary);
        });
}

void OrderExpiryService::processNext(
    const std::shared_ptr<BatchState> &state) const
{
    if (state->nextIndex >= state->orderIds.size())
    {
        auto completion = std::move(state->completion);
        completion(state->summary);
        return;
    }

    auto orderId = state->orderIds[state->nextIndex++];
    lifecycleService_.expireForWorker(
        std::move(orderId),
        [this, state](OrderLifecycleOutcome outcome) {
            if (outcome == OrderLifecycleOutcome::Expired)
                ++state->summary.expired;
            else if (outcome == OrderLifecycleOutcome::Failed)
                ++state->summary.failed;
            else
                ++state->summary.skipped;
            processNext(state);
        });
}
}  // namespace ticketing
