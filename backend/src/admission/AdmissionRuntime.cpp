#include "admission/TrafficControl.h"
#include "admission/AdmissionMetrics.h"
#include "admission/AdmissionRuntime.h"
#include "admission/AdmissionPolicy.h"
#include "admission/AdmissionConfig.h"
#include "security/Crypto.h"
#include <condition_variable>
#include <future>
#include <mutex>
#include <thread>
#include <unordered_map>
namespace ticketing::admission {
namespace {
std::mutex mutex;
std::condition_variable wake;
bool stopping=false,loaded=false,dirty=true;
uint64_t invalidation=0;
std::thread worker;
std::unordered_map<std::string,RuntimePolicy> policies;
std::unordered_map<std::string,std::chrono::steady_clock::time_point> pauses;
std::unordered_map<std::string,std::string> sessions;
std::unordered_map<std::string,std::pair<double,double>> queueSizes;
std::chrono::steady_clock::time_point refreshed;
const std::string scheduleKey="ticketing:admission:schedule";
void reset(const RuntimePolicy &p) {
 auto tx=drogon::app().getDbClient()->newTransaction();
 try {
  const auto before=readPolicy(tx,p.eventId);
  const auto generation=randomHex(16);
  auto changed=tx->execSqlSync("UPDATE event_admission_policies SET queue_generation=$3,policy_version=policy_version+1,updated_at=clock_timestamp() WHERE event_id=$1 AND policy_version=$2 RETURNING event_id",p.eventId,p.version,generation);
  if(changed.empty()){tx->rollback();return;}
  const auto after=readPolicy(tx,p.eventId);
  tx->execSqlSync("INSERT INTO admission_policy_audit(event_id,administrator_id,actor_kind,action,old_version,new_version,old_policy,new_policy) VALUES($1,NULL,'SYSTEM','RESET_GENERATION',$2,$3,$4::jsonb,$5::jsonb)",p.eventId,p.version,p.version+1,admin::encode(before),admin::encode(after));
  auto done=std::make_shared<std::promise<bool>>();auto future=done->get_future();
  tx->setCommitCallback([done](bool ok){done->set_value(ok);});tx.reset();
  if(!future.get())throw std::runtime_error("Admission generation reset commit failed");
 }catch(...){if(tx)tx->rollback();throw;}
}
void refresh(const Config &config) {
 uint64_t epoch;{std::lock_guard lock(mutex);epoch=invalidation;}
 auto db=drogon::app().getDbClient();
 const auto rows=db->execSqlSync(R"SQL(SELECT e.id,e.status,
  (extract(epoch FROM e.sales_starts_at)*1000)::bigint starts,
  (extract(epoch FROM LEAST(e.sales_ends_at,coalesce((SELECT max(s.start_time) FROM sessions s WHERE s.event_id=e.id),e.sales_ends_at)))*1000)::bigint ends,
  p.mode,p.queue_generation,p.policy_version,p.prequeue_seconds,p.max_active_users,p.admission_rate_per_second,p.lease_seconds,
  r.generation initialized_generation FROM events e LEFT JOIN event_admission_policies p ON p.event_id=e.id
  LEFT JOIN admission_runtime_generations r ON r.event_id=e.id ORDER BY e.id LIMIT $1::integer)SQL",config.policyLimit+1);
 if(rows.size()>static_cast<size_t>(config.policyLimit))throw std::runtime_error("Admission registry capacity exceeded");
 bool redisHealthy=true;
 bool needsRedis=false;for(const auto &row:rows)if(!row["mode"].isNull()&&row["mode"].as<std::string>()!="OFF")needsRedis=true;
 if(needsRedis)try{drogon::app().getRedisClient("traffic_control")->execCommandSync<std::string>([](const drogon::nosql::RedisResult &r){return r.asString();},"PING");}catch(...){redisHealthy=false;}
 std::unordered_map<std::string,RuntimePolicy> next;
 std::unordered_map<std::string,std::string> nextSessions;
 int resetCount=0;
 for(const auto &row:rows) {
  RuntimePolicy p;p.eventId=row["id"].as<std::string>();p.published=row["status"].as<std::string>()!="DRAFT";
  p.startsMs=row["starts"].as<int64_t>();p.endsMs=row["ends"].as<int64_t>();
  if(!row["mode"].isNull()) {
   p.mode=row["mode"].as<std::string>();p.version=row["policy_version"].as<int64_t>();p.generation=row["queue_generation"].as<std::string>();
   p.prequeueSeconds=row["prequeue_seconds"].as<int>();p.capacity=row["max_active_users"].as<int>();p.rate=row["admission_rate_per_second"].as<int>();p.leaseSeconds=row["lease_seconds"].as<int>();
  }
  if(redisHealthy && p.mode!="OFF" && p.published && p.endsMs>p.startsMs && p.endsMs>trantor::Date::now().microSecondsSinceEpoch()/1000) {
   const bool bootstrap=row["initialized_generation"].isNull() || row["initialized_generation"].as<std::string>()!=p.generation;
   const auto result=RedisAdmissionStore::run(p,"sync","",bootstrap);
   if(result.empty() || result[0]!="OK") {
    if(!result.empty() && result[0]=="MISSING" && resetCount<config.schedulerBatch){reset(p);++resetCount;}
    if(result.empty() || result[0]=="UNAVAILABLE")redisHealthy=false;
    next.emplace(p.eventId,std::move(p));continue;
   }
   p.redisReady=true;
   if(bootstrap)db->execSqlSync(R"SQL(INSERT INTO admission_runtime_generations(event_id,generation)
    SELECT event_id,queue_generation FROM event_admission_policies WHERE event_id=$1 AND policy_version=$2
    ON CONFLICT(event_id) DO UPDATE SET generation=EXCLUDED.generation,initialized_at=clock_timestamp())SQL",p.eventId,p.version);
   // Cross-slot schedule publication is a separate idempotent step. Refresh repairs
   // a crash between per-event sync and this index update; status never writes it.
   const auto hash=RedisAdmissionStore::eventHash(p.eventId);
   drogon::app().getRedisClient("traffic_control")->execCommandSync<int64_t>([](const drogon::nosql::RedisResult &r){return r.asInteger();},"ZADD %s NX 0 %s",scheduleKey.c_str(),hash.c_str());
  }
  next.emplace(p.eventId,std::move(p));
 }
 const auto sessionRows=db->execSqlSync("SELECT id,event_id FROM sessions ORDER BY id LIMIT $1::integer",config.policyLimit*20+1);
 if(sessionRows.size()>static_cast<size_t>(config.policyLimit*20))throw std::runtime_error("Admission session registry capacity exceeded");
 for(const auto &row:sessionRows)nextSessions.emplace(row["id"].as<std::string>(),row["event_id"].as<std::string>());
 std::lock_guard lock(mutex);
 if(epoch!=invalidation)return;
 policies=std::move(next);sessions=std::move(nextSessions);loaded=true;dirty=false;refreshed=std::chrono::steady_clock::now();
}
void tick(const Config &config) {
 TrafficControl::sample();
 std::unordered_map<std::string,RuntimePolicy> byHash;
 {std::lock_guard lock(mutex);if(!loaded || dirty)return;for(const auto &[id,p]:policies)if(p.mode!="OFF"&&p.published&&p.redisReady&&p.endsMs>trantor::Date::now().microSecondsSinceEpoch()/1000)byHash.emplace(RedisAdmissionStore::eventHash(id),p);}
 if(byHash.empty()){queueSizes.clear();AdmissionMetrics::gauge("ticketing_admission_queue_depth",{},0);AdmissionMetrics::gauge("ticketing_admission_active",{},0);return;}
 const auto redis=drogon::app().getRedisClient("traffic_control");
 std::vector<RuntimePolicy> pending;
 {std::lock_guard lock(mutex);const auto now=std::chrono::steady_clock::now();
  for(auto it=pauses.begin();it!=pauses.end();){if(now>=it->second){it=pauses.erase(it);continue;}const auto p=policies.find(it->first);if(p!=policies.end()&&p->second.redisReady&&pending.size()<static_cast<size_t>(config.schedulerBatch))pending.push_back(p->second);++it;}
 }
 for(const auto &p:pending){const auto key=RedisAdmissionStore::keys(p)[8];
  const auto written=redis->execCommandSync<int64_t>([](const drogon::nosql::RedisResult &r){return r.asInteger();},
   "EVAL %s 1 %s", "if redis.call('EXISTS',KEYS[1])==1 then return 0 end local t=redis.call('TIME');local n=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000);redis.call('SET',KEYS[1],n+5000,'PX',5000);return 1",key.c_str());
  if(written)AdmissionMetrics::count("ticketing_admission_runtime_pauses_total",{});
 }
 const auto due=redis->execCommandSync<std::vector<std::string>>([](const drogon::nosql::RedisResult &r){std::vector<std::string> v;for(const auto &x:r.asArray())v.push_back(x.asString());return v;},"EVAL %s 1 %s %d", "local t=redis.call('TIME');local n=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000);return redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',n,'LIMIT',0,ARGV[1])",scheduleKey.c_str(),config.schedulerBatch);
 for(const auto &hash:due) {
  const auto found=byHash.find(hash);
  if(found==byHash.end()){queueSizes.erase(hash);redis->execCommandSync<int64_t>([](const drogon::nosql::RedisResult &r){return r.asInteger();},"ZREM %s %s",scheduleKey.c_str(),hash.c_str());continue;}
  const auto result=RedisAdmissionStore::run(found->second,"tick");
  if(result.size()<2 || (result[0]!="OK"&&result[0]!="PAUSED")){AdmissionRuntime::invalidate();return;}
  AdmissionMetrics::count("ticketing_admission_scheduler_runs_total",{result.size()>6?result[6]:"OK"});
  if(result.size()>2)AdmissionMetrics::count("ticketing_admission_expirations_total",{},std::stod(result[2]));
  if(result.size()>5)queueSizes[hash]={std::stod(result[4]),std::stod(result[5])};
  const auto next=std::stoll(result[1])+config.schedulerMs;
  redis->execCommandSync<int64_t>([](const drogon::nosql::RedisResult &r){return r.asInteger();},"ZADD %s %lld %s",scheduleKey.c_str(),static_cast<long long>(next),hash.c_str());
 }
 double depth=0,active=0;for(const auto &[hash,size]:queueSizes){depth+=size.first;active+=size.second;}
 AdmissionMetrics::gauge("ticketing_admission_queue_depth",{},depth);AdmissionMetrics::gauge("ticketing_admission_active",{},active);
 redis->execCommandSync<int64_t>([](const drogon::nosql::RedisResult &r){return r.asInteger();},"EXPIRE %s 604800",scheduleKey.c_str());
}
}
void AdmissionRuntime::start() {
 const auto config=Config::parse(drogon::app().getCustomConfig()["admission"]);
 worker=std::thread([config]{
  while(true) {
   bool shouldRefresh;
   {std::lock_guard lock(mutex);if(stopping)break;shouldRefresh=dirty||!loaded||std::chrono::steady_clock::now()-refreshed>std::chrono::milliseconds(config.policyRefreshMs);}
   try{if(shouldRefresh)refresh(config);tick(config);}catch(...){std::lock_guard lock(mutex);dirty=true;}
   std::unique_lock lock(mutex);wake.wait_for(lock,std::chrono::milliseconds(config.schedulerMs),[]{return stopping;});
  }
 });
}
void AdmissionRuntime::stop(){{std::lock_guard lock(mutex);stopping=true;}wake.notify_all();if(worker.joinable())worker.join();}
void AdmissionRuntime::pauseSession(const std::string &session){
 std::lock_guard lock(mutex);const auto event=sessions.find(session);if(event==sessions.end())return;
 const auto p=policies.find(event->second);if(p==policies.end()||p->second.mode=="OFF")return;
 // Registry bounds the cardinality. Repeated rejections do not extend the cooldown.
 pauses.try_emplace(event->second,std::chrono::steady_clock::now()+std::chrono::seconds(5));
}
void AdmissionRuntime::invalidate(){std::lock_guard lock(mutex);dirty=true;++invalidation;}
bool AdmissionRuntime::ready(){std::lock_guard lock(mutex);return loaded&&!dirty&&std::chrono::steady_clock::now()-refreshed<std::chrono::seconds(15);}
std::optional<RuntimePolicy> AdmissionRuntime::policy(const std::string &id){std::lock_guard lock(mutex);const auto p=policies.find(id);return p==policies.end()?std::nullopt:std::optional<RuntimePolicy>(p->second);}
std::optional<std::string> AdmissionRuntime::eventForSession(const std::string &id){std::lock_guard lock(mutex);const auto p=sessions.find(id);return p==sessions.end()?std::nullopt:std::optional<std::string>(p->second);}
}
