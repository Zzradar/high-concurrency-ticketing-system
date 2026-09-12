#include "admission/Bulkhead.h"
#include <barrier>
#include <thread>
#include <vector>
#include <iostream>
int main(){
 using namespace ticketing::admission;
 Bulkhead b;b.configure({2,2,2,2,2,2,2,2});
 auto first=b.acquire(Resource::InventoryWrite),second=b.acquire(Resource::InventoryWrite);
 if(!first||!second||b.acquire(Resource::InventoryWrite))return 1;
 if(!b.acquire(Resource::Financial)||!b.acquire(Resource::Recovery))return 2;
 first.reset();if(!b.acquire(Resource::InventoryWrite))return 3;
 second.reset();if(b.inflight(Resource::InventoryWrite)!=0)return 4;
 std::barrier start(16);std::atomic<unsigned> max{0};std::vector<std::thread> threads;
 for(int i=0;i<16;++i)threads.emplace_back([&]{start.arrive_and_wait();for(int n=0;n<1000;++n){auto p=b.acquire(Resource::InventoryWrite);const auto active=b.inflight(Resource::InventoryWrite);auto seen=max.load();while(active>seen&&!max.compare_exchange_weak(seen,active)){};}});
 for(auto &t:threads)t.join();if(max>2||b.inflight(Resource::InventoryWrite)!=0)return 5;
 try{auto p=b.acquire(Resource::InventoryWrite);throw 1;}catch(...){}
 if(b.inflight(Resource::InventoryWrite)!=0)return 6;
 std::cout<<"Bulkhead concurrency, RAII exception release and independent quotas passed\n";
}
