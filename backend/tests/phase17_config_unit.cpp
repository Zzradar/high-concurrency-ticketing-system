#include "admin/AdminCatalog.h"
#include <iostream>
int main() {
 using ticketing::admin::limits;
 if(limits(Json::Value{}) .seats!=20000)return 1;
 for(auto invalid:{Json::Value(0),Json::Value(-1),Json::Value(true),Json::Value(1.0),Json::Value("20")}) {
  Json::Value v;v["max_seats_per_venue"]=invalid;
  try{(void)limits(v);return 2;}catch(const std::invalid_argument &){}
 }
 Json::Value v;for(auto name:{"max_zones_per_venue","max_rows_per_zone","max_seats_per_row","max_sessions_per_event"})v[name]=2147483647;
 try{(void)limits(v);return 3;}catch(const std::invalid_argument &){}
 std::cout<<"admin config limits passed\n";
}
