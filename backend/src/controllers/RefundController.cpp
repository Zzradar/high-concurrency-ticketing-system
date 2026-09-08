#include "controllers/RefundController.h"
#include "common/ApiResponse.h"
#include "common/AuthContext.h"
namespace
{
auto respond(std::function<void(const drogon::HttpResponsePtr &)> callback)
{
    return [callback](ticketing::RefundResponse result) {
        if (!result.code.empty())
            return callback(ticketing::makeErrorResponse(
                static_cast<drogon::HttpStatusCode>(result.status), result.code, result.code));
        auto response = drogon::HttpResponse::newHttpJsonResponse(result.body);
        response->setStatusCode(static_cast<drogon::HttpStatusCode>(result.status));
        callback(response);
    };
}
} // namespace
void RefundController::request(const drogon::HttpRequestPtr &r,
                               std::function<void(const drogon::HttpResponsePtr &)> &&cb,
                               std::string id) const
{
    if (!r->body().empty())
    {
        cb(ticketing::makeErrorResponse(drogon::k400BadRequest, "INVALID_REQUEST_BODY",
                                        "Refund request body must be empty"));
        return;
    }
    service_.request(id, ticketing::authenticatedUserId(r), respond(std::move(cb)));
}
void RefundController::get(const drogon::HttpRequestPtr &r,
                           std::function<void(const drogon::HttpResponsePtr &)> &&cb,
                           std::string id) const
{
    service_.get(id, ticketing::authenticatedUserId(r), respond(std::move(cb)));
}
