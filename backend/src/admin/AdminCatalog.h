#pragma once
#include <drogon/drogon.h>
#include <functional>
#include <stdexcept>
namespace ticketing::admin {
using DB = drogon::orm::DbClientPtr;
using Reply = std::function<void(const drogon::HttpResponsePtr &)>;
struct Error : std::runtime_error {
    drogon::HttpStatusCode status;
    Error(drogon::HttpStatusCode s,const std::string &code):std::runtime_error(code),status(s){}
};
inline void require(bool condition,const std::string &code="INVALID_ARGUMENT",drogon::HttpStatusCode status=drogon::k400BadRequest) {if(!condition)throw Error(status,code);}
struct Limits {int zones=32, rows=200, seatsPerRow=500, seats=20000, sessions=20;};
Limits limits(const Json::Value &value);
Limits limits();
void fields(const Json::Value &,std::initializer_list<const char *> allowed);
std::string text(const Json::Value &,const char *,size_t max=200,bool empty=false);
std::string timestamp(const Json::Value &,const char *);
Json::Value parse(const std::string &);
std::string encode(const Json::Value &);
std::string id(const char *prefix);
void dispatch(std::function<Json::Value(const DB &)> work,Reply reply,drogon::HttpStatusCode status=drogon::k200OK);
Json::Value venue(const DB &,const std::string &);
void lockVenue(const DB &,const std::string &);
}
