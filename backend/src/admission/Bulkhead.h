#pragma once
#include <array>
#include <atomic>
#include <memory>
#include <stdexcept>
namespace ticketing::admission {
enum class Resource {PublicStaticRead,Admission,Availability,InventoryWrite,Recovery,Financial,Admin,PostgresFallback,Count};
inline constexpr std::array<const char *,8> resourceNames={"PUBLIC_STATIC_READ","ADMISSION","AVAILABILITY","INVENTORY_WRITE","RECOVERY","FINANCIAL","ADMIN","POSTGRES_FALLBACK"};
class Bulkhead {
 std::array<std::atomic<unsigned>,8> active{},peak{};
 std::array<unsigned,8> limits{16,16,16,16,16,16,16,2};
public:
 struct Permit {
  Bulkhead *owner;size_t index;
  ~Permit(){owner->active[index].fetch_sub(1);}
  Permit(const Permit &)=delete;Permit &operator=(const Permit &)=delete;
  Permit(Bulkhead *o,size_t i):owner(o),index(i){}
 };
 void configure(std::array<unsigned,8> values){for(auto v:values)if(v<1||v>256)throw std::invalid_argument("Invalid bulkhead capacity");limits=values;}
 std::shared_ptr<Permit> acquire(Resource resource){
  const auto i=static_cast<size_t>(resource);auto n=active.at(i).load();
  do{if(n>=limits[i])return {};}while(!active[i].compare_exchange_weak(n,n+1));
  auto high=peak[i].load();while(n+1>high&&!peak[i].compare_exchange_weak(high,n+1)){}
  try{return std::make_shared<Permit>(this,i);}catch(...){--active[i];throw;}
 }
 unsigned highWater(Resource resource)const{return peak.at(static_cast<size_t>(resource)).load();}
 unsigned inflight(Resource resource)const{return active.at(static_cast<size_t>(resource)).load();}
};
}
