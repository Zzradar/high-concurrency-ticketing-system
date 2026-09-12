"""Read-only PostgreSQL audit/namespace and Redis qualification invariants. Explicit Phase18 target required."""
import json,hashlib,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
import phase18_admission_http_test as f
QUERIES={
 'policyAuditMismatch':"SELECT count(*) FROM event_admission_policies p LEFT JOIN admission_policy_audit a ON a.event_id=p.event_id AND a.new_version=p.policy_version WHERE a.id IS NULL OR a.new_policy->>'queueGeneration'<>p.queue_generation OR a.new_policy->>'mode'<>p.mode OR (a.new_policy->>'policyVersion')::bigint<>p.policy_version",
 'auditHistoryGap':"SELECT count(*) FROM event_admission_policies p WHERE (SELECT count(*) FROM admission_policy_audit a WHERE a.event_id=p.event_id)<>p.policy_version",
 'auditVersionMismatch':"SELECT count(*) FROM admission_policy_audit WHERE new_version<>old_version+1 OR (new_policy->>'policyVersion')::bigint<>new_version OR (old_policy->>'policyVersion')::bigint<>old_version",
 'namespaceNotRotated':"SELECT count(*) FROM admission_policy_audit WHERE old_version>0 AND action<>'RESET_GENERATION' AND new_policy->>'mode'<>'OFF' AND (CASE old_policy->>'mode' WHEN 'OFF' THEN 'NONE' WHEN 'OBSERVE' THEN 'SHADOW' ELSE 'FORMAL' END)<>(CASE new_policy->>'mode' WHEN 'OBSERVE' THEN 'SHADOW' ELSE 'FORMAL' END) AND old_policy->>'queueGeneration'=new_policy->>'queueGeneration'",
 'formalPositionDiscarded':"SELECT count(*) FROM admission_policy_audit WHERE action<>'RESET_GENERATION' AND old_policy->>'mode' IN ('PAUSED','ENFORCED') AND new_policy->>'mode' IN ('PAUSED','ENFORCED') AND old_policy->>'queueGeneration'<>new_policy->>'queueGeneration'",
 'invalidAuditActor':"SELECT count(*) FROM admission_policy_audit WHERE NOT ((actor_kind='ADMIN' AND administrator_id IS NOT NULL) OR (actor_kind='SYSTEM' AND administrator_id IS NULL AND action='RESET_GENERATION'))"
}
def verify():
 checks={k:int(f.sql(v)) for k,v in QUERIES.items()}
 policies=json.loads(f.sql("SELECT coalesce(json_agg(row_to_json(p)),'[]') FROM (SELECT event_id,mode,queue_generation,policy_version FROM event_admission_policies WHERE mode<>'OFF' AND event_id IN (SELECT e.id FROM events e WHERE e.status<>'DRAFT' AND LEAST(e.sales_ends_at,coalesce((SELECT max(s.start_time) FROM sessions s WHERE s.event_id=e.id),e.sales_ends_at))>clock_timestamp())) p"))
 checks.update(redisNamespaceMismatch=0,duplicateQualification=0,missingKeyTTL=0)
 # No queue creation, heartbeat, expiry cleanup or qualification mutation by the verifier.
 script="local bad=0;for i=1,#KEYS do if redis.call('EXISTS',KEYS[i])==1 and redis.call('PTTL',KEYS[i])<=0 then bad=bad+1 end end;return {redis.call('ZINTERCARD',2,KEYS[2],KEYS[3]),redis.call('ZINTERCARD',2,KEYS[2],KEYS[4]),redis.call('ZINTERCARD',2,KEYS[3],KEYS[4]),bad,redis.call('HGET',KEYS[1],'generation') or '',redis.call('HGET',KEYS[1],'version') or ''}"
 for p in policies:
  root='ticketing:admission:{evt:'+hashlib.sha256(p['event_id'].encode()).hexdigest()+'}:'
  keys=[root+'runtime']+[root+p['queue_generation']+':'+s for s in ['prequeue','waiting','active','presence','heartbeat','sequence','release','pause']]
  result=f.redis('EVAL',script,len(keys),*keys)
  checks['duplicateQualification']+=sum(result[:3]);checks['missingKeyTTL']+=result[3]
  checks['redisNamespaceMismatch']+=int(result[4]!=p['queue_generation'] or result[5]!=str(p['policy_version']))
 result={'passed':not any(checks.values()),'checks':checks,'policiesChecked':len(policies),'limits':['Read-only convergence check: run after workers settle; Redis checks apply only to published policies before effective sales end.','Capacity decreases retain existing leases; historical peak bound is verified by concurrency tests, not inferred from current maxActiveUsers.','Retired generations may remain until their TTL expires.']}
 return result
if __name__=='__main__':
 result=verify();print(json.dumps(result,indent=2));raise SystemExit(not result['passed'])
