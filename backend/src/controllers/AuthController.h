#pragma once

#include "services/AuthService.h"

#include <drogon/HttpController.h>

class AuthController final : public drogon::HttpController<AuthController>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(AuthController::login, "/auth/login", drogon::Post);
    ADD_METHOD_TO(AuthController::me,
                  "/auth/me",
                  drogon::Get,
                  "ticketing::AuthFilter");
    ADD_METHOD_TO(AuthController::logout,
                  "/auth/logout",
                  drogon::Post,
                  "ticketing::AuthFilter");
    METHOD_LIST_END

    void login(const drogon::HttpRequestPtr &request,
               std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
    void me(const drogon::HttpRequestPtr &request,
            std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;
    void logout(const drogon::HttpRequestPtr &request,
                std::function<void(const drogon::HttpResponsePtr &)> &&callback) const;

  private:
    ticketing::AuthService service_;
};
