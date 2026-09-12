#pragma once
#include "admission/AdmissionPolicy.h"
class AdmissionPolicyController : public drogon::HttpController<AdmissionPolicyController> {
public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(AdmissionPolicyController::policy,"/admin/events/{eventId}/admission-policy",
        drogon::Get,drogon::Put,"ticketing::AuthFilter","ticketing::AdminFilter");
    METHOD_LIST_END
    void policy(const drogon::HttpRequestPtr &, ticketing::admin::Reply &&, std::string) const;
};
