#include "observability/AsyncObservation.h"
#include <stdexcept>
#include <thread>
#include <vector>
#include <iostream>
using namespace ticketing;
void require(bool condition) { if(!condition) throw std::runtime_error("observation invariant failed"); }
int main()
{
    double current=0,high=0,oldest=0,elapsed=0;
    int completed=0;
    auto series=std::make_shared<ObservationSeries>([&](double n,double h,double age,double seconds,ObservationOutcome,bool done) {
        current=n;high=h;oldest=age;if(done){++completed;elapsed=seconds;}
    });
    for(auto outcome:{ObservationOutcome::Success,ObservationOutcome::Empty,ObservationOutcome::Error,ObservationOutcome::Timeout}) {
        auto observation=std::make_shared<AsyncObservation>(series);
        require(current==1);
        observation->finish(outcome);observation->finish(outcome);observation.reset();
        require(current==0);
    }
    require(completed==4);
    { AsyncObservation abandoned{series}; }
    require(current==0 && completed==5);
    try { AsyncObservation syncThrow{series};throw std::runtime_error("sync throw"); } catch(const std::runtime_error &) {}
    require(current==0 && completed==6);
    auto shared=std::make_shared<AsyncObservation>(series);
    std::vector<std::thread> threads;
    for(int i=0;i<16;++i) threads.emplace_back([shared]{shared->finish();});
    for(auto &thread:threads) thread.join();
    require(current==0 && completed==7);
    const auto now=ObservationSeries::Clock::now();
    auto a=series->begin(now-std::chrono::seconds(2));
    auto b=series->begin(now-std::chrono::seconds(3));
    series->sample();require(current==2 && high==2 && oldest>=3);
    series->finish(b,now,ObservationOutcome::Success);require(elapsed==3);
    series->finish(a,now,ObservationOutcome::Success);require(elapsed==2 && oldest==0);
    auto broken=std::make_shared<ObservationSeries>([](double,double,double,double,ObservationOutcome,bool){throw std::runtime_error("sink");});
    { AsyncObservation cannotBreakBusiness{broken};cannotBreakBusiness.finish(); }
    std::cout<<"PASS lifetime, duplicate callbacks, concurrent completion, exceptions, oldest and seconds\n";
}
