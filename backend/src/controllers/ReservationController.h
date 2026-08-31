#pragma once

#include "services/ReservationService.h"

#include <drogon/HttpController.h>

class ReservationController final
    : public drogon::HttpController<ReservationController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(ReservationController::createReservation,
                  "/reservations",
                  drogon::Post);
    METHOD_LIST_END

    void createReservation(
        const drogon::HttpRequestPtr &request,
        std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;

  private:
    ticketing::ReservationService service_;
};
