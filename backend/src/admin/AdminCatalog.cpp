#include "admin/AdminCatalog.h"
#include "services/SeatMapComputeExecutor.h"
#include "common/ApiResponse.h"
#include <future>
#include <regex>
#include <set>
#include <sstream>
#include <limits>
namespace ticketing::admin {
Limits limits(const Json::Value &v) {
    Limits result;
    if(v.isNull())return result;
    if(!v.isObject())throw std::invalid_argument("admin_catalog must be an object");
    const std::pair<const char *,int *> values[]={{"max_zones_per_venue",&result.zones},{"max_rows_per_zone",&result.rows},{"max_seats_per_row",&result.seatsPerRow},{"max_seats_per_venue",&result.seats},{"max_sessions_per_event",&result.sessions}};
    for(auto [key,target]:values)if(v.isMember(key)) {
        if((v[key].type()!=Json::intValue && v[key].type()!=Json::uintValue) || !v[key].isInt() || v[key].asInt()<=0)throw std::invalid_argument(std::string("Invalid admin_catalog.")+key);
        *target=v[key].asInt();
    }
    int64_t product=result.zones;
    for(int factor:{result.rows,result.seatsPerRow,result.sessions}) {
        if(product>std::numeric_limits<int64_t>::max()/factor)throw std::invalid_argument("admin_catalog multiplication overflow");
        product*=factor;
    }
    return result;
}
Limits limits(){return limits(drogon::app().getCustomConfig()["admin_catalog"]);}
void fields(const Json::Value &v,std::initializer_list<const char *> allowed) {
    require(v.isObject());std::set<std::string> names;for(auto name:allowed)names.insert(name);
    for(const auto &key:v.getMemberNames())require(names.count(key)!=0);
}
std::string text(const Json::Value &v,const char *key,size_t max,bool empty) {
    require(v[key].isString());auto s=v[key].asString();auto a=s.find_first_not_of(" \t\r\n"),b=s.find_last_not_of(" \t\r\n");
    s=a==std::string::npos?"":s.substr(a,b-a+1);require((empty||!s.empty())&&s.size()<=max&&s.find('\0')==std::string::npos);return s;
}
std::string timestamp(const Json::Value &v,const char *key) {
    auto s=text(v,key,40);static const std::regex pattern(R"(^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$)");require(std::regex_match(s,pattern));return s;
}
Json::Value parse(const std::string &s){Json::Value v;Json::CharReaderBuilder b;std::istringstream in(s);std::string errors;if(!Json::parseFromStream(b,in,&v,&errors))throw std::runtime_error("Invalid database JSON");return v;}
std::string encode(const Json::Value &v){Json::StreamWriterBuilder b;b["indentation"]="";return Json::writeString(b,v);}
std::string id(const char *prefix){return std::string(prefix)+drogon::utils::getUuid();}
void dispatch(std::function<Json::Value(const DB &)> work,Reply reply,drogon::HttpStatusCode status) {
    // Separate bounded workers: synchronous admin I/O never blocks public HTTP loops.
    static SeatMapComputeExecutor workers(2,32);
    auto done=std::make_shared<Reply>(std::move(reply));
    auto failure=[done]{(*done)(makeErrorResponse(drogon::k503ServiceUnavailable,"ADMIN_BUSY","Admin capacity unavailable"));};
    if(!workers.trySubmit([work=std::move(work),done,status]{
        std::shared_ptr<drogon::orm::Transaction> tx;
        try {
            tx=drogon::app().getDbClient()->newTransaction();
            auto result=work(tx);
            auto committed=std::make_shared<std::promise<bool>>();auto future=committed->get_future();
            tx->setCommitCallback([committed](bool ok){committed->set_value(ok);});tx.reset();
            if(!future.get())throw std::runtime_error("Admin commit failed");
            auto response=drogon::HttpResponse::newHttpJsonResponse(result);response->setStatusCode(status);(*done)(response);
        } catch(const Error &e) {if(tx)tx->rollback();(*done)(makeErrorResponse(e.status,e.what(),e.what()));}
        catch(const drogon::orm::DrogonDbException &e) {
            if(tx)tx->rollback();
            LOG_ERROR<<"Admin transaction: "<<e.base().what();
            // User timestamps are checked by PostgreSQL, including calendar validity.
            const auto *sql=dynamic_cast<const drogon::orm::SqlError *>(&e.base());
            const bool input=sql && (sql->sqlState()=="22007" || sql->sqlState()=="22008");
            (*done)(makeErrorResponse(input?drogon::k400BadRequest:drogon::k500InternalServerError,input?"INVALID_ARGUMENT":"INTERNAL_ERROR","Admin transaction failed"));
        } catch(const std::exception &e) {if(tx)tx->rollback();LOG_ERROR<<e.what();(*done)(makeErrorResponse(drogon::k500InternalServerError,"INTERNAL_ERROR","Admin transaction failed"));}
    },failure))failure();
}
void lockVenue(const DB &db,const std::string &id) {require(!db->execSqlSync("SELECT id FROM venues WHERE id=$1 FOR UPDATE",id).empty(),"VENUE_NOT_FOUND",drogon::k404NotFound);}
Json::Value venue(const DB &db,const std::string &id) {
    auto rows=db->execSqlSync(R"SQL(SELECT jsonb_build_object('id',v.id,'name',v.name,'city',v.city,
        'totalSeats',(SELECT count(*) FROM seats WHERE venue_id=v.id),
        'zoneCount',(SELECT count(*) FROM venue_zones WHERE venue_id=v.id),
        'frozen',EXISTS(SELECT 1 FROM session_seats WHERE venue_id=v.id),
        'zones',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',z.id,'code',z.code,'name',z.name,'sortOrder',z.sort_order,
          'seatCount',(SELECT count(*) FROM seats WHERE zone_id=z.id),
          'rows',COALESCE((SELECT jsonb_agg(jsonb_build_object('label',r.row_no,'seatCount',r.n) ORDER BY r.row_no) FROM (SELECT row_no,count(*) n FROM seats WHERE zone_id=z.id GROUP BY row_no) r),'[]'::jsonb)) ORDER BY z.sort_order) FROM venue_zones z WHERE z.venue_id=v.id),'[]'::jsonb)) AS data FROM venues v WHERE v.id=$1)SQL",id);
    require(!rows.empty(),"VENUE_NOT_FOUND",drogon::k404NotFound);return parse(rows[0]["data"].as<std::string>());
}
}
