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

void OrderController::cancelOrder(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string orderId) const
{
    using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.cancelOrder(
        orderId,
        request->getHeader("X-User-Id"),
        [callbackPtr](ticketing::CancelOrderResult result) {
            using ticketing::CancelOrderOutcome;
            if (result.outcome == CancelOrderOutcome::Cancelled && result.value)
            {
                (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(
                    result.value->toJson()));
                return;
            }
            if (result.outcome == CancelOrderOutcome::InvalidArgument)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k400BadRequest, "INVALID_ARGUMENT", "Invalid order request"));
                return;
            }
            if (result.outcome == CancelOrderOutcome::NotFound)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "ORDER_NOT_FOUND", "Order not found"));
                return;
            }
            if (result.outcome == CancelOrderOutcome::NotCancellable)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k409Conflict, "ORDER_NOT_CANCELLABLE", "Order is not cancellable"));
                return;
            }
            if (result.outcome == CancelOrderOutcome::OrderExpired)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k409Conflict, "ORDER_EXPIRED", "Order has expired"));
                return;
            }
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR", "Internal server error"));
        });
}

void OrderController::payOrder(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string orderId) const
{
    using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    paymentService_.startPayment(
        std::move(orderId), request->getHeader("X-User-Id"),
        [callbackPtr](ticketing::StartPaymentResult result) {
            using ticketing::StartPaymentOutcome;
            if ((result.outcome == StartPaymentOutcome::Started ||
                 result.outcome == StartPaymentOutcome::AlreadyPaid) && result.value)
            {
                auto response = drogon::HttpResponse::newHttpJsonResponse(
                    result.value->toJson());
                response->setStatusCode(result.outcome == StartPaymentOutcome::Started
                                            ? drogon::k202Accepted
                                            : drogon::k200OK);
                (*callbackPtr)(response);
                return;
            }
            if (result.outcome == StartPaymentOutcome::InvalidArgument)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k400BadRequest, "INVALID_ARGUMENT", "Invalid payment request"));
                return;
            }
            if (result.outcome == StartPaymentOutcome::NotFound)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "ORDER_NOT_FOUND", "Order not found"));
                return;
            }
            if (result.outcome == StartPaymentOutcome::NotPayable)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k409Conflict, "ORDER_NOT_PAYABLE", "Order is not payable"));
                return;
            }
            if (result.outcome == StartPaymentOutcome::OrderExpired)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k409Conflict, "ORDER_EXPIRED", "Order has expired"));
                return;
            }
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR", "Internal server error"));
        });
}
