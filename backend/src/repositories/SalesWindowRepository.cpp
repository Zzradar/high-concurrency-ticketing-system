#include "repositories/SalesWindowRepository.h"
#include <drogon/drogon.h>
namespace ticketing
{
void SalesWindowRepository::readSessionGate(
    const std::shared_ptr<drogon::orm::Transaction> &transaction,const std::string &sessionId,
    std::function<void(std::optional<SessionSalesGate>)> onSuccess,std::function<void()> onError) const
{
    constexpr const char *sql=R"SQL(
        WITH sales_clock AS MATERIALIZED (SELECT clock_timestamp() AS now)
        SELECT session.event_id,event.status AS event_status,session.status AS session_status,
            CASE WHEN LEAST(event.sales_ends_at,session.start_time)<=event.sales_starts_at THEN 'ENDED'
                 WHEN sales_clock.now<event.sales_starts_at THEN 'NOT_STARTED'
                 WHEN sales_clock.now>=LEAST(event.sales_ends_at,session.start_time) THEN 'ENDED'
                 ELSE 'OPEN' END AS sales_state,
            GREATEST(0,FLOOR(EXTRACT(EPOCH FROM
                (LEAST(event.sales_ends_at,session.start_time)-sales_clock.now))*1000))::BIGINT AS remaining_milliseconds
        FROM sessions AS session JOIN events AS event ON event.id=session.event_id
        CROSS JOIN sales_clock WHERE session.id=$1
    )SQL";
    transaction->execSqlAsync(sql,
        [onSuccess=std::move(onSuccess)](const drogon::orm::Result &rows){
            if(rows.empty()){onSuccess(std::nullopt);return;}
            const auto &row=rows.front();const auto state=row["sales_state"].as<std::string>();
            onSuccess(SessionSalesGate{row["event_id"].as<std::string>(),row["event_status"].as<std::string>(),
                row["session_status"].as<std::string>(),state=="OPEN"?SalesWindowState::Open:
                state=="NOT_STARTED"?SalesWindowState::NotStarted:SalesWindowState::Ended,
                row["remaining_milliseconds"].as<std::int64_t>()});
        },[onError=std::move(onError)](const drogon::orm::DrogonDbException &){
            LOG_ERROR<<"Failed to read sales window";onError();},sessionId);
}
}
