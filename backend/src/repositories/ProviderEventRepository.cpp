#include "repositories/ProviderEventRepository.h"

#include <drogon/drogon.h>

namespace ticketing
{
void ProviderEventRepository::insert(
    const drogon::orm::DbClientPtr &client, ProviderEventRecord event,
    std::function<void(bool)> onSuccess, std::function<void()> onError) const
{
    client->execSqlAsync(
        "INSERT INTO payment_provider_events "
        "(id, provider, provider_event_id, event_type, object_kind, provider_object_id, "
        "local_reference_id, status, received_at, next_retry_at, payload_sha256) "
        "VALUES ($1,$2,$3,$4,$5,NULLIF($6,''),NULLIF($7,''),'PENDING',clock_timestamp(),clock_timestamp(),$8) "
        "ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &rows) {
            onSuccess(!rows.empty());
        },
        [onError = std::move(onError)](const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Provider event inbox insert failed: " << error.base().what();
            onError();
        }, event.id, event.provider, event.providerEventId, event.eventType,
        event.objectKind, event.providerObjectId, event.localReferenceId,
        event.payloadSha256);
}
}  // namespace ticketing
