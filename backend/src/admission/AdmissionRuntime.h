#pragma once
#include "admission/RedisAdmissionStore.h"
#include <optional>
namespace ticketing::admission {
class AdmissionRuntime {
public:
 static void start();
 static void stop();
 static void invalidate();
 static void pauseSession(const std::string &session);
 static bool ready();
 static std::optional<RuntimePolicy> policy(const std::string &eventId);
 static std::optional<std::string> eventForSession(const std::string &sessionId);
};
}
