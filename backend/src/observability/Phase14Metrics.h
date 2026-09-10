#pragma once
#include "observability/AsyncObservation.h"
#include <drogon/drogon.h>
#include <utility>

namespace ticketing
{
class Phase14Metrics final
{
  public:
    enum class Flow { Auth, SeatRead, Checkout, Reservation, Order, PaymentControl, Refund, Other, Count };
    enum class RedisOperation { HoldWrite, HoldRead, AuthRead, AuthWrite, AuthDelete, LoginCheck, LoginFailure, LoginClear, Count };
    static void registerWithApplication();
    static std::shared_ptr<AsyncObservation> transaction(Flow flow);
    static std::shared_ptr<AsyncObservation> redis(RedisOperation operation);
    static void expiry(double seconds, std::size_t scanned, std::size_t expired, std::size_t skipped, std::size_t failed);

    template<class Client, class Callback>
    static void newTransactionAsync(const Client &client, Flow flow, Callback callback)
    {
        auto observation = transaction(flow);
        try {
            client->newTransactionAsync([observation, callback=std::move(callback)](const auto &tx) mutable {
                if (observation) observation->finish(tx ? ObservationOutcome::Success : ObservationOutcome::Empty);
                callback(tx);
            });
        } catch (...) {
            if (observation) observation->finish(ObservationOutcome::Error);
            throw;
        }
    }

    template<class Client, class Success, class Error, class... Args>
    static void execCommandAsync(const Client &client, RedisOperation operation, Success success, Error error, Args&&... args)
    {
        auto observation = redis(operation);
        try {
            client->execCommandAsync(
                [observation, success=std::move(success)](const drogon::nosql::RedisResult &result) mutable {
                    // Compound transport duration ends at callback entry. Downstream
                    // parsing/conflict/rollback cannot leak this observation.
                    if (observation) observation->finish();
                    success(result);
                },
                [observation, error=std::move(error)](const std::exception &exception) mutable {
                    const auto *redisError = dynamic_cast<const drogon::nosql::RedisException *>(&exception);
                    if (observation) observation->finish(redisError && redisError->code() == drogon::nosql::RedisErrorCode::kTimeout
                        ? ObservationOutcome::Timeout : ObservationOutcome::Error);
                    error(exception);
                }, std::forward<Args>(args)...);
        } catch (...) {
            if (observation) observation->finish(ObservationOutcome::Error);
            throw;
        }
    }
};
} // namespace ticketing
