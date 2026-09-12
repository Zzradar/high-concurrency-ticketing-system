#pragma once
#include <drogon/drogon.h>
#include <drogon/plugins/PromExporter.h>
#include <drogon/utils/monitoring/Counter.h>
#include <drogon/utils/monitoring/Gauge.h>
namespace ticketing::admission {
// Call sites supply only fixed request classes, modes and enumerated outcomes.
struct AdmissionMetrics {
 static void count(const char *name,std::vector<std::string> labels={},double amount=1) noexcept {
  try {auto plugin=drogon::app().getPlugin<drogon::plugin::PromExporter>();if(!plugin)return;
   auto collector=plugin->getCollector<drogon::monitoring::Counter>(name);if(collector)collector->metric(labels)->increment(amount);
  }catch(...){}
 }
 static void gauge(const char *name,std::vector<std::string> labels,double value) noexcept {
  try {auto plugin=drogon::app().getPlugin<drogon::plugin::PromExporter>();if(!plugin)return;
   auto collector=plugin->getCollector<drogon::monitoring::Gauge>(name);if(collector)collector->metric(labels)->set(value);
  }catch(...){}
 }
};
}
