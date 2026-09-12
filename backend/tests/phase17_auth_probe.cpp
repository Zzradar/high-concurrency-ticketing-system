// Test-only route: compiled solely with TICKETING_PHASE17_EXTERNAL_TESTS.
#include <drogon/HttpController.h>
#include "common/AuthContext.h"
class Phase17AuthProbe : public drogon::HttpController<Phase17AuthProbe>
{
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(Phase17AuthProbe::probe, "/admin/phase17-auth-probe", drogon::Get, drogon::Post,
                  "ticketing::AuthFilter", "ticketing::AdminFilter");
    METHOD_LIST_END
    void probe(const drogon::HttpRequestPtr &request,
               std::function<void(const drogon::HttpResponsePtr &)> &&callback) const
    {
        Json::Value body;
        body["role"] = ticketing::authContext(request)->role;
        callback(drogon::HttpResponse::newHttpJsonResponse(body));
    }
};
