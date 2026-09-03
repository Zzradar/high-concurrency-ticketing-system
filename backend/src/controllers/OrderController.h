#pragma once

#include "services/OrderService.h"
#include "services/PaymentService.h"

#include <drogon/HttpController.h>

#include <string>

class OrderController final : public drogon::HttpController<OrderController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(OrderController::getOrder,
                  "/orders/{orderId}",
                  drogon::Get);
    ADD_METHOD_TO(OrderController::cancelOrder,
                  "/orders/{orderId}/cancel",
                  drogon::Post);
    ADD_METHOD_TO(OrderController::payOrder,
                  "/orders/{orderId}/pay",
                  drogon::Post);
    METHOD_LIST_END

    void getOrder(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string orderId) const;

    void cancelOrder(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string orderId) const;

    void payOrder(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string orderId) const;

  private:
    ticketing::OrderService service_;
    ticketing::PaymentService paymentService_;
};
