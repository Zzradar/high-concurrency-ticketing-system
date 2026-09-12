#include "admission/AdmissionPolicy.h"
#include "security/Crypto.h"
#include <cstdlib>
#include <set>

namespace ticketing::admission {
namespace {
std::int64_t integer(const Json::Value &v, std::int64_t low, std::int64_t high) {
    admin::require((v.type()==Json::intValue || v.type()==Json::uintValue) && v.isInt64());
    const auto n=v.asInt64(); admin::require(n>=low && n<=high); return n;
}
}
PolicyInput parsePolicyInput(const Json::Value &v) {
    admin::fields(v,{"mode","prequeueSeconds","maxActiveUsers","admissionRatePerSecond","leaseSeconds","expectedPolicyVersion"});
    admin::require(v["mode"].isString()); const auto mode=v["mode"].asString();
    admin::require(mode=="OFF" || mode=="OBSERVE" || mode=="ENFORCED" || mode=="PAUSED");
    return {mode,static_cast<int>(integer(v["prequeueSeconds"],0,86400)),
        static_cast<int>(integer(v["maxActiveUsers"],1,1000000)),
        static_cast<int>(integer(v["admissionRatePerSecond"],1,100000)),
        static_cast<int>(integer(v["leaseSeconds"],10,3600)),
        integer(v["expectedPolicyVersion"],0,9007199254740990LL)};
}
bool validSecret(std::string_view value) {
    // Operators supply >=32 random bytes encoded as hex. Never print this value.
    if(value.size()<64 || value.size()>256 || value.size()%2) return false;
    for(char c:value) if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')||(c>='A'&&c<='F'))) return false;
    return std::set<char>(value.begin(),value.end()).size()>=8;
}
bool secretAvailable() {
    const auto value=std::getenv("TICKETING_ADMISSION_HMAC_SECRET");
    return value && validSecret(value);
}
Json::Value defaultPolicy(const std::string &eventId) {
    Json::Value p; p["eventId"]=eventId; p["mode"]="OFF"; p["policyVersion"]=0;
    for(const auto key:{"prequeueSeconds","maxActiveUsers","admissionRatePerSecond","leaseSeconds","queueGeneration","createdAt","updatedAt","updatedBy"}) p[key]=Json::nullValue;
    return p;
}
Json::Value readPolicy(const admin::DB &db, const std::string &eventId) {
    const auto rows=db->execSqlSync(R"SQL(SELECT jsonb_build_object(
      'eventId',event_id,'mode',mode,'prequeueSeconds',prequeue_seconds,
      'maxActiveUsers',max_active_users,'admissionRatePerSecond',admission_rate_per_second,
      'leaseSeconds',lease_seconds,'policyVersion',policy_version,'queueGeneration',queue_generation,
      'createdAt',to_char(created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      'updatedAt',to_char(updated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      'updatedBy',updated_by) data FROM event_admission_policies WHERE event_id=$1)SQL",eventId);
    if(!rows.empty()) return admin::parse(rows[0]["data"].as<std::string>());
    admin::require(!db->execSqlSync("SELECT id FROM events WHERE id=$1",eventId).empty(),"EVENT_NOT_FOUND",drogon::k404NotFound);
    return defaultPolicy(eventId);
}
Json::Value writePolicy(const admin::DB &db, const std::string &eventId,
                        const Json::Value &body, const std::string &userId) {
    const auto p=parsePolicyInput(body);
    admin::require(p.mode=="OFF" || secretAvailable(),"ADMISSION_SECRET_UNAVAILABLE",drogon::k503ServiceUnavailable);
    const auto before=readPolicy(db,eventId);
    admin::require(before["policyVersion"].asInt64()==p.expectedVersion,"POLICY_VERSION_CONFLICT",drogon::k409Conflict);
    const auto oldMode=before["mode"].asString();
    const auto generation=p.expectedVersion==0 || (p.mode=="ENFORCED" && (oldMode=="OFF" || oldMode=="OBSERVE"))
        ? randomHex(16) : before["queueGeneration"].asString();
    bool changed=false;
    if(p.expectedVersion==0) {
        changed=!db->execSqlSync(R"SQL(INSERT INTO event_admission_policies
          (event_id,mode,prequeue_seconds,max_active_users,admission_rate_per_second,lease_seconds,policy_version,queue_generation,updated_by)
          VALUES($1,$2,$3,$4,$5,$6,1,$7,$8) ON CONFLICT(event_id) DO NOTHING RETURNING policy_version)SQL",
          eventId,p.mode,p.prequeueSeconds,p.maxActiveUsers,p.admissionRatePerSecond,p.leaseSeconds,generation,userId).empty();
    } else {
        changed=!db->execSqlSync(R"SQL(UPDATE event_admission_policies SET mode=$2,prequeue_seconds=$3,
          max_active_users=$4,admission_rate_per_second=$5,lease_seconds=$6,queue_generation=$7,
          updated_by=$8,updated_at=clock_timestamp(),policy_version=policy_version+1
          WHERE event_id=$1 AND policy_version=$9 RETURNING policy_version)SQL",
          eventId,p.mode,p.prequeueSeconds,p.maxActiveUsers,p.admissionRatePerSecond,p.leaseSeconds,generation,userId,p.expectedVersion).empty();
    }
    admin::require(changed,"POLICY_VERSION_CONFLICT",drogon::k409Conflict);
    auto after=readPolicy(db,eventId);
    db->execSqlSync(R"SQL(INSERT INTO admission_policy_audit
      (event_id,administrator_id,action,old_version,new_version,old_policy,new_policy)
      VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb))SQL",eventId,userId,
      std::string(p.expectedVersion==0?"CREATE":"UPDATE"),p.expectedVersion,p.expectedVersion+1,
      admin::encode(before),admin::encode(after));
    return after;
}
}
