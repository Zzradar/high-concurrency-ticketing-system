#include "services/CheckoutOwnershipCache.h"
#include "services/SeatAvailabilityReadModel.h"
#include <drogon/drogon.h>
#include <atomic>
#include <memory>

namespace ticketing
{
void CheckoutOwnershipCache::lookup(const std::string &checkout,const std::string &user,const std::string &session,
                                    std::function<void(std::string)> hit,std::function<void()> miss)
{
    auto claimed=std::make_shared<std::atomic_bool>(false);
    auto fallback=std::make_shared<std::function<void()>>(std::move(miss));
    try
    {
        drogon::app().getRedisClient("seat_holds")->execCommandAsync(
            [checkout,user,session,hit=std::move(hit),claimed,fallback](const drogon::nosql::RedisResult &result){
                std::optional<std::string> own;
                try
                {
                    if(!result.isNil())
                    {
                        const auto raw=result.asString();Json::CharReaderBuilder builder;
                        auto reader=std::unique_ptr<Json::CharReader>(builder.newCharReader());Json::Value value;std::string errors;
                        if(reader->parse(raw.data(),raw.data()+raw.size(),&value,&errors) && value.isObject() &&
                           value["userId"].isString() && value["sessionId"].isString())
                            own=value["userId"].asString()==user && value["sessionId"].asString()==session ? checkout : std::string{};
                    }
                }
                catch(...){}
                if(claimed->exchange(true))return;
                if(own)hit(*own);else (*fallback)();
            },[claimed,fallback](const drogon::nosql::RedisException &){if(!claimed->exchange(true))(*fallback)();},
            "GET %s",("ticketing:checkout-owner:{"+checkout+"}").c_str());
    }
    catch(...){if(!claimed->exchange(true))(*fallback)();}
}
void CheckoutOwnershipCache::store(const std::string &checkout,const std::string &user,const std::string &session)
{
    Json::Value value;value["userId"]=user;value["sessionId"]=session;
    Json::StreamWriterBuilder writer;writer["indentation"]="";const auto raw=Json::writeString(writer,value);
    try
    {
        drogon::app().getRedisClient("seat_holds")->execCommandAsync(
            [](const drogon::nosql::RedisResult &){},[](const drogon::nosql::RedisException &){},
            "SET %s %b EX %d",("ticketing:checkout-owner:{"+checkout+"}").c_str(),raw.data(),raw.size(),
            SeatAvailabilityConfig::load().ownerCacheTtlSeconds);
    }
    catch(...){} // best effort; PostgreSQL remains the authorization source on misses.
}
}
