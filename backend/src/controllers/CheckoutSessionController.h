#pragma once

#include "services/CheckoutSessionService.h"

#include <drogon/HttpController.h>

#include <string>

class CheckoutSessionController final
    : public drogon::HttpController<CheckoutSessionController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(CheckoutSessionController::create,
                  "/checkout-sessions",
                  drogon::Post);
    ADD_METHOD_TO(CheckoutSessionController::list,
                  "/checkout-sessions",
                  drogon::Get);
    ADD_METHOD_TO(CheckoutSessionController::get,
                  "/checkout-sessions/{id}",
                  drogon::Get);
    ADD_METHOD_TO(CheckoutSessionController::replaceSeats,
                  "/checkout-sessions/{id}/seats",
                  drogon::Put);
    ADD_METHOD_TO(CheckoutSessionController::confirm,
                  "/checkout-sessions/{id}/confirm",
                  drogon::Post);
    ADD_METHOD_TO(CheckoutSessionController::abandon,
                  "/checkout-sessions/{id}/abandon",
                  drogon::Post);
    METHOD_LIST_END

    void create(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
    void list(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
    void get(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string id) const;
    void replaceSeats(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string id) const;
    void confirm(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string id) const;
    void abandon(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string id) const;

  private:
    ticketing::CheckoutSessionService service_;
};
