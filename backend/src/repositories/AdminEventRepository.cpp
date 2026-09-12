#include "repositories/AdminEventRepository.h"
#include <set>
namespace ticketing {
using namespace admin;
namespace {
Json::Value event(const DB &db,const std::string &id) {
    auto rows=db->execSqlSync(R"SQL(SELECT jsonb_build_object('id',e.id,'name',e.name,'description',e.description,'category',e.category,'coverUrl',e.cover_url,
        'venueId',e.primary_venue_id,'status',e.status,'dateRange',e.date_range,
        'salesStartsAt',to_char(e.sales_starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'salesEndsAt',to_char(e.sales_ends_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'publishedAt',to_char(e.published_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'publishedBy',e.published_by,
        'sessions',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',s.id,'status',s.status,'venueId',s.venue_id,'hallName',s.hall_name,
         'startTime',to_char(s.start_time AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
         'gateTime',to_char(s.gate_time AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
         'prices',COALESCE((SELECT jsonb_agg(jsonb_build_object('zoneId',p.zone_id,'price',p.price) ORDER BY z.sort_order) FROM session_zone_prices p JOIN venue_zones z ON z.id=p.zone_id WHERE p.session_id=s.id),'[]'::jsonb)) ORDER BY s.start_time,s.id) FROM sessions s WHERE s.event_id=e.id),'[]'::jsonb)) data
         FROM events e WHERE e.id=$1)SQL",id);
    require(!rows.empty(),"EVENT_NOT_FOUND",drogon::k404NotFound);return parse(rows[0]["data"].as<std::string>());
}
void displayFields(const Json::Value &body,Json::Value &e,bool patch) {
    for(auto field:{"name","description","category","coverUrl"})
        if(!patch||body.isMember(field))e[field]=text(body,field,std::string(field)=="description"?10000:std::string(field)=="coverUrl"?2000:200,std::string(field)=="description");
}
void updateDisplay(const DB &db,const Json::Value &e) {
    db->execSqlSync("UPDATE events SET name=$2,description=$3,category=$4,cover_url=$5 WHERE id=$1",e["id"].asString(),e["name"].asString(),e["description"].asString(),e["category"].asString(),e["coverUrl"].asString());
}
void window(const DB &db,const Json::Value &b) {
    require(db->execSqlSync("SELECT $1::timestamptz < $2::timestamptz ok",timestamp(b,"salesStartsAt"),timestamp(b,"salesEndsAt"))[0]["ok"].as<bool>());
}
}
Json::Value AdminEventRepository::list(const DB &db) {
    Json::Value result(Json::arrayValue);
    for(auto row:db->execSqlSync(R"SQL(SELECT jsonb_build_object('id',e.id,'name',e.name,'status',e.status,'venueId',e.primary_venue_id,'venueName',v.name,'sessionCount',(SELECT count(*) FROM sessions WHERE event_id=e.id)) data FROM events e JOIN venues v ON v.id=e.primary_venue_id ORDER BY e.created_at DESC,e.id)SQL"))result.append(parse(row["data"].as<std::string>()));
    return result;
}
Json::Value AdminEventRepository::preview(const DB &db,const Json::Value &e) {
    Json::Value result;result["eventId"]=e["id"];result["status"]=e["status"];auto v=venue(db,e["venueId"].asString());
    result["venue"]=v;result["sessionCount"]=e["sessions"].size();result["expectedSessionSeatCount"]=Json::Int64(v["totalSeats"].asInt64()*e["sessions"].size());result["issues"]=Json::Value(Json::arrayValue);result["sessions"]=Json::Value(Json::arrayValue);
    auto issue=[&](const char *code,std::string session="",std::string zone="") {Json::Value i;i["code"]=code;i["message"]=code;if(!session.empty())i["sessionId"]=session;if(!zone.empty())i["zoneId"]=zone;result["issues"].append(i);};
    if(e["sessions"].empty())issue("NO_SESSIONS");
    if(v["totalSeats"].asInt64()==0||v["zones"].empty())issue("VENUE_EMPTY");
    if(db->execSqlSync("SELECT sales_ends_at<=clock_timestamp() ended FROM events WHERE id=$1",e["id"].asString())[0]["ended"].as<bool>())issue("EVENT_WINDOW_ENDED");
    for(const auto &s:e["sessions"]) {
        auto sid=s["id"].asString();auto checks=db->execSqlSync(R"SQL(SELECT start_time>clock_timestamp() future,gate_time<start_time gate,
          LEAST(e.sales_ends_at,s.start_time)>e.sales_starts_at AS window_ok FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.id=$1)SQL",sid);
        if(!checks[0]["future"].as<bool>())issue("SESSION_START_NOT_FUTURE",sid);
        if(!checks[0]["gate"].as<bool>())issue("SESSION_GATE_INVALID",sid);
        if(!checks[0]["window_ok"].as<bool>())issue("SESSION_WINDOW_EMPTY",sid);
        if(s["venueId"]!=e["venueId"])issue("SESSION_VENUE_MISMATCH",sid);
        std::map<std::string,int64_t> prices;for(auto p:s["prices"])prices[p["zoneId"].asString()]=p["price"].asInt64();
        for(const auto &z:v["zones"]) {auto zid=z["id"].asString();if(!prices.count(zid))issue("ZONE_PRICE_MISSING",sid,zid);else if(prices[zid]<=0)issue("ZONE_PRICE_INVALID",sid,zid);}
        Json::Value session;session["id"]=sid;session["startTime"]=s["startTime"];session["configuredZones"]=Json::UInt64(prices.size());session["requiredZones"]=v["zones"].size();result["sessions"].append(session);
    }
    result["publishable"]=e["status"]=="DRAFT"&&result["issues"].empty();return result;
}
Json::Value AdminEventRepository::detail(const DB &db,const std::string &id) {auto e=event(db,id);e["venue"]=venue(db,e["venueId"].asString());e["readiness"]=preview(db,e);return e;}
Json::Value AdminEventRepository::execute(const DB &db,const std::string &action,std::string eid,const std::string &sid,const Json::Value &body,const std::string &user) {
    if(action=="list")return list(db);
    if(action=="detail"||action=="preview") {
        db->execSqlSync("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
        return action=="detail"?detail(db,eid):preview(db,event(db,eid));
    }
    if(action=="create") {
        fields(body,{"name","description","category","coverUrl","venueId","salesStartsAt","salesEndsAt"});Json::Value e;displayFields(body,e,false);window(db,body);
        auto vid=text(body,"venueId");lockVenue(db,vid);auto v=venue(db,vid);require(v["totalSeats"].asInt64()>0&&!v["zones"].empty());eid=id("EVT-");
        db->execSqlSync("INSERT INTO events(id,primary_venue_id,name,description,category,cover_url,date_range,status,sales_starts_at,sales_ends_at) VALUES($1,$2,$3,$4,$5,$6,'','DRAFT',$7::timestamptz,$8::timestamptz)",eid,vid,e["name"].asString(),e["description"].asString(),e["category"].asString(),e["coverUrl"].asString(),timestamp(body,"salesStartsAt"),timestamp(body,"salesEndsAt"));return detail(db,eid);
    }
    require(!db->execSqlSync("SELECT id FROM events WHERE id=$1 FOR UPDATE",eid).empty(),"EVENT_NOT_FOUND",drogon::k404NotFound);
    auto e=event(db,eid);auto vid=e["venueId"].asString();
    if(action=="display") {fields(body,{"name","description","category","coverUrl"});displayFields(body,e,true);updateDisplay(db,e);return detail(db,eid);}
    if(action=="publish"&&e["status"]=="ON_SALE") {
        Json::Value result;result["disposition"]="ALREADY_PUBLISHED";result["event"]=detail(db,eid);
        auto count=db->execSqlSync("SELECT count(*) n FROM session_seats i JOIN sessions s ON s.id=i.session_id WHERE s.event_id=$1",eid)[0]["n"].as<int64_t>();
        result["inventory"]["sessionCount"]=e["sessions"].size();result["inventory"]["seatCountPerSession"]=venue(db,vid)["totalSeats"];result["inventory"]["sessionSeatCount"]=Json::Int64(count);return result;
    }
    require(e["status"]=="DRAFT",action=="publish"?"EVENT_NOT_PUBLISHABLE":"EVENT_NOT_EDITABLE",drogon::k409Conflict);
    if(action=="update") {
        fields(body,{"name","description","category","coverUrl","venueId","salesStartsAt","salesEndsAt"});auto target=text(body,"venueId");require(target==vid||e["sessions"].empty(),"EVENT_VENUE_LOCKED",drogon::k409Conflict);
        lockVenue(db,target);auto v=venue(db,target);require(v["totalSeats"].asInt64()>0&&!v["zones"].empty());window(db,body);displayFields(body,e,false);updateDisplay(db,e);
        db->execSqlSync("UPDATE events SET primary_venue_id=$2,sales_starts_at=$3::timestamptz,sales_ends_at=$4::timestamptz WHERE id=$1",eid,target,timestamp(body,"salesStartsAt"),timestamp(body,"salesEndsAt"));return detail(db,eid);
    }
    // Every session/price mutation locks Venue before touching rows that plan replacement deletes.
    lockVenue(db,vid);e=event(db,eid);
    if(action=="publish") {
        auto p=preview(db,e);require(p["publishable"].asBool(),"EVENT_NOT_PUBLISHABLE",drogon::k409Conflict);
        for(auto s:e["sessions"])require(s["status"]=="DRAFT","EVENT_NOT_PUBLISHABLE",drogon::k409Conflict);
        auto count=db->execSqlSync(R"SQL(INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price,current_reservation_id)
          SELECT 'SS-'||s.id||'-'||seat.id,s.id,seat.id,s.venue_id,'AVAILABLE',p.price,NULL
          FROM sessions s JOIN session_zone_prices p ON p.session_id=s.id AND p.venue_id=s.venue_id
          JOIN seats seat ON seat.zone_id=p.zone_id AND seat.venue_id=s.venue_id WHERE s.event_id=$1 AND s.status='DRAFT')SQL",eid).affectedRows();
        require(count==static_cast<size_t>(p["expectedSessionSeatCount"].asInt64()),"INTERNAL_ERROR",drogon::k500InternalServerError);
        db->execSqlSync("UPDATE sessions SET status='ON_SALE' WHERE event_id=$1 AND status='DRAFT'",eid);
        db->execSqlSync(R"SQL(UPDATE events SET status='ON_SALE',published_at=clock_timestamp(),published_by=$2,
          date_range=(SELECT to_char(min(start_time) AT TIME ZONE 'Asia/Shanghai','YYYY.MM.DD') || CASE WHEN (min(start_time) AT TIME ZONE 'Asia/Shanghai')::date=(max(start_time) AT TIME ZONE 'Asia/Shanghai')::date THEN '' ELSE ' — '||to_char(max(start_time) AT TIME ZONE 'Asia/Shanghai','YYYY.MM.DD') END FROM sessions WHERE event_id=$1) WHERE id=$1)SQL",eid,user);
        Json::Value result;result["disposition"]="PUBLISHED_NOW";result["event"]=detail(db,eid);result["inventory"]["sessionCount"]=e["sessions"].size();result["inventory"]["seatCountPerSession"]=p["venue"]["totalSeats"];result["inventory"]["sessionSeatCount"]=Json::UInt64(count);return result;
    }
    std::string sessionId=sid;
    if(action=="session-create")require(e["sessions"].size()<static_cast<unsigned>(limits().sessions));
    else {
        auto rows=db->execSqlSync("SELECT status FROM sessions WHERE id=$1 AND event_id=$2",sid,eid);
        require(!rows.empty(),"SESSION_NOT_FOUND",drogon::k404NotFound);require(rows[0]["status"].as<std::string>()=="DRAFT","SESSION_NOT_EDITABLE",drogon::k409Conflict);
    }
    if(action=="session-create"||action=="session-update") {
        fields(body,{"hallName","startTime","gateTime"});auto hall=text(body,"hallName"),start=timestamp(body,"startTime"),gate=timestamp(body,"gateTime");
        require(db->execSqlSync("SELECT $1::timestamptz < $2::timestamptz AND $2::timestamptz>sales_starts_at ok FROM events WHERE id=$3",gate,start,eid)[0]["ok"].as<bool>());
        if(action=="session-create") {sessionId=id("SES-");db->execSqlSync("INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES($1,$2,$3,$4,$5::timestamptz,$6::timestamptz,'DRAFT')",sessionId,eid,vid,hall,start,gate);}
        else db->execSqlSync("UPDATE sessions SET hall_name=$2,start_time=$3::timestamptz,gate_time=$4::timestamptz WHERE id=$1",sid,hall,start,gate);
    } else if(action=="session-delete")db->execSqlSync("DELETE FROM sessions WHERE id=$1 AND event_id=$2",sid,eid);
    else if(action=="prices") {
        fields(body,{"prices"});require(body["prices"].isArray());std::set<std::string> seen,allowed;auto v=venue(db,vid);for(auto z:v["zones"])allowed.insert(z["id"].asString());
        for(auto p:body["prices"]) {fields(p,{"zoneId","price"});auto zid=text(p,"zoneId");require(allowed.count(zid)&&seen.insert(zid).second);auto price=p["price"];require((price.type()==Json::intValue||price.type()==Json::uintValue)&&price.isInt64()&&price.asInt64()>0);}
        db->execSqlSync("DELETE FROM session_zone_prices WHERE session_id=$1",sid);
        db->execSqlSync(R"SQL(INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) SELECT $1,p->>'zoneId',$2,(p->>'price')::bigint FROM jsonb_array_elements($3::jsonb) p)SQL",sid,vid,encode(body["prices"]));
    } else throw Error(drogon::k400BadRequest,"INVALID_ARGUMENT");
    auto result=detail(db,eid);result["savedSessionId"]=sessionId;return result;
}
}
