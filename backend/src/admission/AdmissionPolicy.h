#pragma once
#include "admin/AdminCatalog.h"
#include <cstdint>

namespace ticketing::admission {
enum class QualificationNamespace { None, Shadow, Formal };
QualificationNamespace qualificationNamespace(std::string_view mode);
bool rotatesGeneration(std::string_view oldMode, std::string_view newMode);
struct PolicyInput {
    std::string mode;
    int prequeueSeconds, maxActiveUsers, admissionRatePerSecond, leaseSeconds;
    std::int64_t expectedVersion;
};
PolicyInput parsePolicyInput(const Json::Value &body);
bool validSecret(std::string_view value);
bool secretAvailable();
Json::Value defaultPolicy(const std::string &eventId);
Json::Value readPolicy(const admin::DB &db, const std::string &eventId);
Json::Value writePolicy(const admin::DB &db, const std::string &eventId,
                        const Json::Value &body, const std::string &userId);
}
