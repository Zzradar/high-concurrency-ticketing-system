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
}  // namespace ticketing
