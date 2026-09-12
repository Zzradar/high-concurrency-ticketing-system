#include "services/AdminVenueService.h"
#include <set>
#include <regex>
namespace ticketing {
Json::Value AdminVenueService::validate(const Json::Value &body) {
    using namespace admin;fields(body,{"name","city","zones"});auto cfg=limits();Json::Value plan;
    plan["name"]=text(body,"name");plan["city"]=text(body,"city",100);
    require(body["zones"].isArray()&&!body["zones"].empty()&&body["zones"].size()<=static_cast<unsigned>(cfg.zones));
    std::set<std::string> codes,names;int64_t total=0;plan["zones"]=Json::Value(Json::arrayValue);
    for(const auto &z:body["zones"]) {
        fields(z,{"code","name","rows"});Json::Value zone;auto code=text(z,"code",32);
        for(auto &c:code)if(c>='a'&&c<='z')c=static_cast<char>(c-'a'+'A');
        require(std::regex_match(code,std::regex("[A-Z0-9_-]{1,32}"))&&codes.insert(code).second);
        auto name=text(z,"name",100);require(names.insert(name).second);zone["code"]=code;zone["name"]=name;
        require(z["rows"].isArray()&&!z["rows"].empty()&&z["rows"].size()<=static_cast<unsigned>(cfg.rows));
        std::set<std::string> labels;zone["rows"]=Json::Value(Json::arrayValue);
        for(const auto &r:z["rows"]) {
            fields(r,{"label","seatCount"});auto label=text(r,"label",16);require(labels.insert(label).second);
            require((r["seatCount"].type()==Json::intValue || r["seatCount"].type()==Json::uintValue)&&r["seatCount"].isInt()&&r["seatCount"].asInt()>0&&r["seatCount"].asInt()<=cfg.seatsPerRow);
            total+=r["seatCount"].asInt();require(total<=cfg.seats);
            Json::Value row;row["label"]=label;row["seatCount"]=r["seatCount"];zone["rows"].append(row);
        }
        plan["zones"].append(zone);
    }
    return plan;
}
}
