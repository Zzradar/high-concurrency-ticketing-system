#pragma once
#include "services/RefundService.h"
#include <drogon/HttpController.h>
class RefundController final : public drogon::HttpController<RefundController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(RefundController::request, "/orders/{orderId}/refunds", drogon::Post,
                  "ticketing::AuthFilter");
    ADD_METHOD_TO(RefundController::get, "/refunds/{refundId}", drogon::Get,
                  "ticketing::AuthFilter");
    METHOD_LIST_END
    void request(const drogon::HttpRequestPtr &,
                 std::function<void(const drogon::HttpResponsePtr &)> &&, std::string) const;
    void get(const drogon::HttpRequestPtr &,
             std::function<void(const drogon::HttpResponsePtr &)> &&, std::string) const;

  private:
    ticketing::RefundService service_;
};
