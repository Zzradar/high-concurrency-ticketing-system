#include "controllers/OrderController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

void OrderController::getOrder(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string orderId) const
{
    using HttpCallback =
        std::function<void(const drogon::HttpResponsePtr &)>;
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));

    service_.getOrder(
        orderId,
        request->getHeader("X-User-Id"),
        [callbackPtr](ticketing::GetOrderResult result) {
            using ticketing::GetOrderOutcome;
            switch (result.outcome)
            {
                case GetOrderOutcome::Found:
                    if (result.value)
                    {
                        (*callbackPtr)(
                            drogon::HttpResponse::newHttpJsonResponse(
                                result.value->toJson()));
                        return;
                    }
                    break;
                case GetOrderOutcome::InvalidArgument:
                    (*callbackPtr)(ticketing::makeErrorResponse(
                        drogon::k400BadRequest,
                        "INVALID_ARGUMENT",
                        "Invalid order request"));
                    return;
                case GetOrderOutcome::NotFound:
                    (*callbackPtr)(ticketing::makeErrorResponse(
                        drogon::k404NotFound,
                        "ORDER_NOT_FOUND",
                        "Order not found"));
                    return;
                case GetOrderOutcome::InternalError:
                    break;
            }

            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError,
                "INTERNAL_ERROR",
                "Internal server error"));
        });
}
