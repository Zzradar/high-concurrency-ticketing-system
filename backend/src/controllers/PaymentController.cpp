#include "controllers/PaymentController.h"

#include "common/ApiResponse.h"

#include <memory>
#include <utility>

void PaymentController::getAttempt(
    const drogon::HttpRequestPtr &request,
    std::function<void(const drogon::HttpResponsePtr &)> &&callback,
    std::string paymentAttemptId) const
{
    using HttpCallback = std::function<void(const drogon::HttpResponsePtr &)>;
    auto callbackPtr = std::make_shared<HttpCallback>(std::move(callback));
    service_.getPaymentAttempt(
        std::move(paymentAttemptId), request->getHeader("X-User-Id"),
        [callbackPtr](ticketing::GetPaymentAttemptResult result) {
            using ticketing::GetPaymentAttemptOutcome;
            if (result.outcome == GetPaymentAttemptOutcome::Found && result.value)
            {
                (*callbackPtr)(drogon::HttpResponse::newHttpJsonResponse(
                    result.value->toJson()));
                return;
            }
            if (result.outcome == GetPaymentAttemptOutcome::InvalidArgument)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k400BadRequest, "INVALID_ARGUMENT", "Invalid payment attempt request"));
                return;
            }
            if (result.outcome == GetPaymentAttemptOutcome::NotFound)
            {
                (*callbackPtr)(ticketing::makeErrorResponse(
                    drogon::k404NotFound, "PAYMENT_ATTEMPT_NOT_FOUND", "Payment attempt not found"));
                return;
            }
            (*callbackPtr)(ticketing::makeErrorResponse(
                drogon::k500InternalServerError, "INTERNAL_ERROR", "Internal server error"));
        });
}
