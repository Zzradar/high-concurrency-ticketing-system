#include "repositories/AdminVenueRepository.h"
namespace ticketing {
using namespace admin;
Json::Value AdminVenueRepository::list(const DB &db) {
    Json::Value result(Json::arrayValue);
    for(const auto &r:db->execSqlSync(R"SQL(SELECT jsonb_build_object('id',v.id,'name',v.name,'city',v.city,
       'totalSeats',(SELECT count(*) FROM seats WHERE venue_id=v.id),'zoneCount',(SELECT count(*) FROM venue_zones WHERE venue_id=v.id),
       'frozen',EXISTS(SELECT 1 FROM session_seats WHERE venue_id=v.id)) data FROM venues v ORDER BY v.created_at DESC,v.id)SQL"))result.append(parse(r["data"].as<std::string>()));
    return result;
}
Json::Value AdminVenueRepository::save(const DB &db,std::string venueId,const Json::Value &plan) {
    bool reset=false;
    if(venueId.empty()) {venueId=id("VEN-");db->execSqlSync("INSERT INTO venues(id,name,city) VALUES($1,$2,$3)",venueId,plan["name"].asString(),plan["city"].asString());}
    else {
        lockVenue(db,venueId);
        require(!db->execSqlSync("SELECT EXISTS(SELECT 1 FROM session_seats WHERE venue_id=$1) frozen",venueId)[0]["frozen"].as<bool>(),"VENUE_SEAT_PLAN_FROZEN",drogon::k409Conflict);
        reset=db->execSqlSync("DELETE FROM session_zone_prices p USING sessions s WHERE p.session_id=s.id AND s.venue_id=$1 AND s.status='DRAFT'",venueId).affectedRows()>0;
        db->execSqlSync("DELETE FROM seats WHERE venue_id=$1",venueId);
        db->execSqlSync("DELETE FROM venue_zones WHERE venue_id=$1",venueId);
        db->execSqlSync("UPDATE venues SET name=$2,city=$3 WHERE id=$1",venueId,plan["name"].asString(),plan["city"].asString());
    }
    auto zones=plan["zones"];int64_t expected=0;
    for(auto &zone:zones){zone["id"]=id("VZ-");for(const auto &row:zone["rows"])expected+=row["seatCount"].asInt64();}
    auto encoded=encode(zones);
    db->execSqlSync(R"SQL(INSERT INTO venue_zones(id,venue_id,code,name,sort_order)
      SELECT z->>'id',$1,z->>'code',z->>'name',(ordinal-1)::integer FROM jsonb_array_elements($2::jsonb) WITH ORDINALITY a(z,ordinal))SQL",venueId,encoded);
    auto inserted=db->execSqlSync(R"SQL(INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label)
      SELECT z->>'id'||'-'||row_ordinal||'-'||n,$1,z->>'id',r->>'label',n,(r->>'label')||lpad(n::text,3,'0')
      FROM jsonb_array_elements($2::jsonb) z
      CROSS JOIN LATERAL jsonb_array_elements(z->'rows') WITH ORDINALITY rows(r,row_ordinal)
      CROSS JOIN LATERAL generate_series(1,(r->>'seatCount')::integer) n)SQL",venueId,encoded).affectedRows();
    require(inserted==static_cast<size_t>(expected),"INTERNAL_ERROR",drogon::k500InternalServerError);
    auto result=venue(db,venueId);result["pricingReset"]=reset;return result;
}
}
