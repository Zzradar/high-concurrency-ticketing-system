#pragma once
#include "admin/AdminCatalog.h"
namespace ticketing::admission {
class AdmissionService {
public:
 static void request(std::string eventId,std::string userId,std::string operation,
                     std::string expectedGeneration,admin::Reply reply);
 // Completion returns null when the caller may continue to PostgreSQL's final checks.
 static void guard(std::string sessionId,std::string userId,admin::Reply completion);
 static void stop();
};
}
