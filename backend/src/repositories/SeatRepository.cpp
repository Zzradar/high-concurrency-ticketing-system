#include "security/Crypto.h"
#include "repositories/SeatRepository.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>

#include <utility>

namespace ticketing
{
namespace {
std::string layoutTag(const drogon::orm::Row &row) {
    std::string identity="seat-layout-v2";
    for(const auto key:{"layout_session_id","venue_id","created","published","layout_revision"}) {
        const auto value=row[key].as<std::string>();
        identity+=std::to_string(value.size())+":"+value;
    }
    return "W/\"seat-layout-v2-"+sha256Hex(identity)+"\"";
}
}
void SeatRepository::publicLayoutIdentity(const std::string &sessionId,
    std::function<void(std::optional<std::string>)> onSuccess,ErrorCallback onError) const {
    // Visibility and validator share one PostgreSQL statement snapshot.
    drogon::app().getDbClient("default")->execSqlAsync(
        "SELECT s.id layout_session_id,s.venue_id,(extract(epoch FROM s.created_at)*1000000)::bigint created,coalesce((extract(epoch FROM e.published_at)*1000000)::bigint,0) published,r.revision layout_revision FROM sessions s JOIN events e ON e.id=s.event_id JOIN session_layout_revisions r ON r.session_id=s.id WHERE s.id=$1 AND s.status<>'DRAFT' AND e.status<>'DRAFT'",
        [onSuccess=std::move(onSuccess)](const drogon::orm::Result &rows){
            if(rows.empty()){onSuccess(std::nullopt);return;}
            onSuccess(layoutTag(rows[0]));
        },[onError=std::move(onError)](const drogon::orm::DrogonDbException &){onError();},sessionId);
}

void SeatRepository::listBySessionId(
    const std::string &sessionId,
    std::function<void(std::vector<SeatRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT
            inventory.id,
            inventory.session_id,
            seat.seat_label,
            seat.row_no,
            seat.seat_no,
            inventory.status,
            zone.name AS zone,
            inventory.price
        FROM session_seats AS inventory
        JOIN seats AS seat ON seat.id = inventory.seat_id
        JOIN venue_zones AS zone ON zone.id = seat.zone_id AND zone.venue_id = seat.venue_id
        WHERE inventory.session_id = $1 AND EXISTS(SELECT 1 FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.id=$1 AND s.status<>'DRAFT' AND e.status<>'DRAFT')
        ORDER BY zone.sort_order ASC,
                 seat.row_no ASC,
                 seat.seat_no ASC,
                 inventory.id ASC
    )SQL";

    const auto started = PerformanceMetrics::seatMapStart();
    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [started, onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            PerformanceMetrics::observeSeatMap(
                PerformanceMetrics::SeatMapStage::DbFetchAndMaterialize, started);
            const auto rowsStarted = PerformanceMetrics::seatMapStart();
            std::vector<SeatRow> seats;
            seats.reserve(result.size());
            for (const auto &row : result)
            {
                seats.push_back(SeatRow{
                    .id = row["id"].as<std::string>(),
                    .sessionId = row["session_id"].as<std::string>(),
                    .label = row["seat_label"].as<std::string>(),
                    .row = row["row_no"].as<std::string>(),
                    .number = row["seat_no"].as<std::int32_t>(),
                    .status = row["status"].as<std::string>(),
                    .zone = row["zone"].as<std::string>(),
                    .price = row["price"].as<std::int64_t>(),
                });
            }
            PerformanceMetrics::observeSeatMap(
                PerformanceMetrics::SeatMapStage::RowBuild, rowsStarted);
            onSuccess(std::move(seats));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list session seats: "
                      << error.base().what();
            onError();
        },
        sessionId);
}

void SeatRepository::listLayoutBySessionId(
    const std::string &sessionId,
    std::function<void(std::optional<SeatLayoutSnapshot>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT layout_identity.*, layout_rows.*
        FROM (
            SELECT s.id layout_session_id,s.venue_id,
                (extract(epoch FROM s.created_at)*1000000)::bigint created,
                coalesce((extract(epoch FROM e.published_at)*1000000)::bigint,0) published,
                r.revision layout_revision
            FROM sessions s JOIN events e ON e.id=s.event_id
            JOIN session_layout_revisions r ON r.session_id=s.id
            WHERE s.id=$1 AND s.status<>'DRAFT' AND e.status<>'DRAFT'
        ) AS layout_identity
        LEFT JOIN LATERAL (
            SELECT inventory.id,seat.seat_label,seat.row_no,seat.seat_no,
                   zone.name AS zone,inventory.price,zone.sort_order
            FROM session_seats AS inventory
            JOIN seats AS seat ON seat.id=inventory.seat_id
            JOIN venue_zones AS zone ON zone.id=seat.zone_id AND zone.venue_id=seat.venue_id
            WHERE inventory.session_id=layout_identity.layout_session_id
        ) AS layout_rows ON true
        ORDER BY layout_rows.sort_order,layout_rows.row_no,layout_rows.seat_no,layout_rows.id
    )SQL";

    const auto started = PerformanceMetrics::seatMapStart();
    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [started, onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &result) {
            if(result.empty()){onSuccess(std::nullopt);return;}
            SeatLayoutSnapshot snapshot{layoutTag(result[0]),{}};
            auto &seats=snapshot.seats;
            seats.reserve(result.size());
            for (const auto &row : result)
            {
                if(row["id"].isNull())continue; // Visible empty Layout still carries its snapshot tag.
                seats.push_back(SeatLayoutRow{
                    .id = row["id"].as<std::string>(),
                    .label = row["seat_label"].as<std::string>(),
                    .row = row["row_no"].as<std::string>(),
                    .number = row["seat_no"].as<std::int32_t>(),
                    .zone = row["zone"].as<std::string>(),
                    .price = row["price"].as<std::int64_t>(),
                });
            }
            PerformanceMetrics::observeSeatMap(
                PerformanceMetrics::SeatMapStage::LayoutDbFetchAndMaterialize,
                started);
            onSuccess(std::move(snapshot));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list session seat layout: "
                      << error.base().what();
            onError();
        },
        sessionId);
}

void SeatRepository::listAvailabilityBySessionId(
    const std::string &sessionId,
    std::function<void(std::vector<SeatAvailabilityRow>)> onSuccess,
    ErrorCallback onError) const
{
    constexpr const char *sql = R"SQL(
        SELECT id, status
        FROM session_seats
        WHERE session_id = $1 AND EXISTS(SELECT 1 FROM sessions s WHERE s.id=$1 AND s.status<>'DRAFT' AND s.event_id IN (SELECT id FROM events WHERE status<>'DRAFT'))
        ORDER BY id ASC
    )SQL";

    const auto started = PerformanceMetrics::seatMapStart();
    drogon::app().getDbClient("default")->execSqlAsync(
        sql,
        [started, onSuccess = std::move(onSuccess)](
            const drogon::orm::Result &result) {
            std::vector<SeatAvailabilityRow> seats;
            seats.reserve(result.size());
            for (const auto &row : result)
            {
                seats.push_back(SeatAvailabilityRow{
                    .id = row["id"].as<std::string>(),
                    .status = row["status"].as<std::string>(),
                });
            }
            PerformanceMetrics::observeSeatMap(
                PerformanceMetrics::SeatMapStage::AvailabilityDbFetchAndMaterialize,
                started);
            onSuccess(std::move(seats));
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to list session seat availability: "
                      << error.base().what();
            onError();
        },
        sessionId);
}

void SeatRepository::sessionExists(
    const std::string &sessionId,
    std::function<void(bool)> onSuccess,
    ErrorCallback onError) const
{
    drogon::app().getDbClient("default")->execSqlAsync(
        "SELECT EXISTS(SELECT 1 FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.id=$1 AND s.status<>'DRAFT' AND e.status<>'DRAFT') AS found",
        [onSuccess = std::move(onSuccess)](const drogon::orm::Result &result) {
            onSuccess(result.front()["found"].as<bool>());
        },
        [onError = std::move(onError)](
            const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Failed to check session existence: "
                      << error.base().what();
            onError();
        },
        sessionId);
}
}  // namespace ticketing
