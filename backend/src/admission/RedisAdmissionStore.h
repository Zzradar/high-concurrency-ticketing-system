#pragma once
#include <drogon/drogon.h>
#include <array>
#include <string>
#include <vector>
namespace ticketing::admission {
struct RuntimePolicy {
 std::string eventId,mode="OFF",generation;
 int64_t version=0,startsMs=0,endsMs=0;
 int prequeueSeconds=0,capacity=0,rate=0,leaseSeconds=0;
 bool published=false, redisReady=false;
};
class RedisAdmissionStore {
public:
 using Result=std::vector<std::string>;
 static std::string eventHash(const std::string &eventId);
 static std::array<std::string,9> keys(const RuntimePolicy &policy);
 // Blocking only on dedicated admission workers/scheduler, never Drogon I/O loops.
 static Result run(const RuntimePolicy &policy,const std::string &operation,
                   const std::string &userId="",bool bootstrap=false);
};
}
