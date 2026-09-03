#pragma once

#include "services/SeatService.h"
#include "services/AuthSessionService.h"
#include "repositories/CheckoutSessionRepository.h"

#include <drogon/HttpController.h>

#include <string>

class SeatController final : public drogon::HttpController<SeatController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(SeatController::listSessionSeats,
                  "/sessions/{sessionId}/seats",
                  drogon::Get);
    METHOD_LIST_END

    void listSessionSeats(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback,
        std::string sessionId) const;

  private:
    void listWithOwnCheckout(
        const std::string &sessionId,
        const std::string &checkoutSessionId,
        const std::shared_ptr<std::function<void(const drogon::HttpResponsePtr &)>> &callback) const;

    ticketing::SeatService service_;
    ticketing::AuthSessionService authService_;
    ticketing::CheckoutSessionRepository checkoutRepository_;
};
