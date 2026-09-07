#pragma once

#include "repositories/ProviderEventRepository.h"

#include <drogon/HttpController.h>

class StripeWebhookController final
    : public drogon::HttpController<StripeWebhookController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(StripeWebhookController::receive,
                  "/payment-webhooks/stripe", drogon::Post);
    METHOD_LIST_END

    void receive(const drogon::HttpRequestPtr &request,
                 std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
  private:
    ticketing::ProviderEventRepository repository_;
};
