#pragma once

#include <drogon/orm/DbClient.h>

#include <functional>
#include <string>

namespace ticketing
{
struct ProviderEventRecord
{
    std::string id;
    std::string provider;
    std::string providerEventId;
    std::string eventType;
    std::string objectKind;
    std::string providerObjectId;
    std::string localReferenceId;
    std::string payloadSha256;
};

class ProviderEventRepository
{
  public:
    void insert(const drogon::orm::DbClientPtr &client, ProviderEventRecord event,
                std::function<void(bool inserted)> onSuccess,
                std::function<void()> onError) const;
};
}  // namespace ticketing
