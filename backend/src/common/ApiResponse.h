#pragma once

#include <drogon/HttpResponse.h>

#include <string>

namespace ticketing
{
inline drogon::HttpResponsePtr makeErrorResponse(
    drogon::HttpStatusCode status,
    const std::string &code,
    const std::string &message)
{
    Json::Value body;
    body["code"] = code;
    body["message"] = message;

    auto response = drogon::HttpResponse::newHttpJsonResponse(body);
    response->setStatusCode(status);
    return response;
}
}  // namespace ticketing
