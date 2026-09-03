#include "services/OrderService.h"

#include <drogon/drogon.h>

#include <memory>
#include <utility>

namespace ticketing
{
void OrderService::getOrder(const std::string &orderId,
                            const std::string &userId,
                            Completion completion) const
{
    if (orderId.empty() || userId.empty())
    {
        completion(GetOrderResult{
            .outcome = GetOrderOutcome::InvalidArgument,
            .value = std::nullopt,
        });
        return;
    }

    auto completionPtr = std::make_shared<Completion>(std::move(completion));
    auto client = drogon::app().getDbClient("default");
    repository_.userExists(
        client,
        userId,
        [this, client, orderId, userId, completionPtr](bool exists) {
            if (!exists)
            {
                (*completionPtr)(GetOrderResult{
                    .outcome = GetOrderOutcome::InvalidArgument,
                    .value = std::nullopt,
                });
                return;
            }

            repository_.findByIdForUser(
                client,
                orderId,
                userId,
                [completionPtr](std::optional<TicketOrder> order) {
                    if (!order)
                    {
                        (*completionPtr)(GetOrderResult{
                            .outcome = GetOrderOutcome::NotFound,
                            .value = std::nullopt,
                        });
                        return;
                    }
                    (*completionPtr)(GetOrderResult{
                        .outcome = GetOrderOutcome::Found,
                        .value = std::move(order),
                    });
                },
                [completionPtr] {
                    (*completionPtr)(GetOrderResult{
                        .outcome = GetOrderOutcome::InternalError,
                        .value = std::nullopt,
                    });
                });
        },
        [completionPtr] {
            (*completionPtr)(GetOrderResult{
                .outcome = GetOrderOutcome::InternalError,
                .value = std::nullopt,
            });
        });
}

void OrderService::cancelOrder(
    const std::string &orderId,
    const std::string &userId,
    std::function<void(CancelOrderResult)> completion) const
{
    if (orderId.empty() || userId.empty())
    {
        completion({CancelOrderOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto completionPtr =
        std::make_shared<std::function<void(CancelOrderResult)>>(std::move(completion));
    lifecycleService_.cancel(
        orderId,
        userId,
        [this, orderId, userId, completionPtr](OrderLifecycleOutcome outcome) {
            if (outcome == OrderLifecycleOutcome::Cancelled ||
                outcome == OrderLifecycleOutcome::AlreadyCancelled)
            {
                auto client = drogon::app().getDbClient("default");
                repository_.findByIdForUser(
                    client, orderId, userId,
                    [completionPtr](std::optional<TicketOrder> order) {
                        (*completionPtr)({order ? CancelOrderOutcome::Cancelled
                                                : CancelOrderOutcome::InternalError,
                                          std::move(order)});
                    },
                    [completionPtr] {
                        (*completionPtr)({CancelOrderOutcome::InternalError,
                                          std::nullopt});
                    });
                return;
            }
            CancelOrderOutcome mapped = CancelOrderOutcome::InternalError;
            if (outcome == OrderLifecycleOutcome::NotFound)
                mapped = CancelOrderOutcome::NotFound;
            else if (outcome == OrderLifecycleOutcome::NotCancellable)
                mapped = CancelOrderOutcome::NotCancellable;
            else if (outcome == OrderLifecycleOutcome::OrderExpired)
                mapped = CancelOrderOutcome::OrderExpired;
            (*completionPtr)({mapped, std::nullopt});
        });
}
}  // namespace ticketing
