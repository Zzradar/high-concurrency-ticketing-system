#pragma once

#include "services/OrderService.h"

#include <drogon/HttpController.h>

#include <string>

class OrderController final : public drogon::HttpController<OrderController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(OrderController::getOrder,
                  "/orders/{orderId}",
                  drogon::Get);
    METHOD_LIST_END

    void getOrder(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string orderId) const;

  private:
    ticketing::OrderService service_;
};
