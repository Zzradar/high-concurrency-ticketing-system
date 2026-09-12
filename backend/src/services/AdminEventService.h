#pragma once
#include "repositories/AdminEventRepository.h"
namespace ticketing {
class AdminEventService {
 public:
 static void handle(std::string action,std::string eventId,std::string sessionId,Json::Value body,std::string user,admin::Reply reply);
};
}
