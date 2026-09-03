#pragma once

#include "services/PaymentService.h"

#include <drogon/HttpController.h>

class PaymentController final
    : public drogon::HttpController<PaymentController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(PaymentController::getAttempt,
                  "/payment-attempts/{paymentAttemptId}",
                  drogon::Get,
                  "ticketing::AuthFilter");
    METHOD_LIST_END

    void getAttempt(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string paymentAttemptId) const;

  private:
    ticketing::PaymentService service_;
};
