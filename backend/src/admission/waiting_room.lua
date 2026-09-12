-- All nine keys share one safely hashed event hash tag. No cross-slot commands.
-- KEYS: runtime, prequeue, waiting, presence, active, heartbeat, sequence, release, pause
-- ARGV: operation, generation, policyVersion, mode, prequeueStartMs, salesStartMs,
-- salesEndMs, maxActive, releasePerSecond, leaseMs, presenceMs, heartbeatMs,
-- memberHash, stableRandomScore, batch, allowBootstrap
local op, generation, version, mode = ARGV[1], ARGV[2], tonumber(ARGV[3]), ARGV[4]
local prestart, starts, ends = tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7])
local capacity, rate, lease, presence, heartbeat = tonumber(ARGV[8]), tonumber(ARGV[9]), tonumber(ARGV[10]), tonumber(ARGV[11]), tonumber(ARGV[12])
local member, score, batch = ARGV[13], tonumber(ARGV[14]), tonumber(ARGV[15])
if not version or not batch or batch < 1 or batch > 256 or not capacity or capacity < 1 or capacity > 1000000 or not rate or rate < 1 or rate > 100000 or not lease or lease < 10000 or lease > 3600000 or not presence or presence < 10000 or presence > 120000 or not heartbeat or heartbeat < 1000 or heartbeat > 10000 or not prestart or not starts or not ends or prestart > starts or starts >= ends then return {'INVALID'} end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2])/1000)
local ttl = math.min(ends + lease + presence, now + 604800000)
local function touch()
 for i=1,9 do if redis.call('EXISTS',KEYS[i]) == 1 then redis.call('PEXPIREAT',KEYS[i],ttl) end end
end
if op == 'sync' then
 local previous=tonumber(redis.call('HGET',KEYS[1],'version') or '0')
 if previous > version then return {'STALE',tostring(now)} end
 if previous == 0 and ARGV[16] ~= '1' then return {'MISSING',tostring(now)} end
 if previous == version and redis.call('HGET',KEYS[1],'generation') ~= generation then return {'STALE',tostring(now)} end
 redis.call('HSET',KEYS[1],'generation',generation,'version',version,'mode',mode)
 touch()
 return {'OK',tostring(now)}
end
if redis.call('HGET',KEYS[1],'generation') ~= generation or tonumber(redis.call('HGET',KEYS[1],'version') or '0') ~= version or redis.call('HGET',KEYS[1],'mode') ~= mode then return {'RESET_REQUIRED',tostring(now)} end
if mode=='OFF' then return {'NOT_REQUIRED',tostring(now)} end
local function remove(id)
 for _,i in ipairs({2,3,4,5}) do redis.call('ZREM',KEYS[i],id) end
 redis.call('HDEL',KEYS[6],id)
end
local function state()
 if now >= ends then return {'SALES_ENDED',tostring(now)} end
 local active=tonumber(redis.call('ZSCORE',KEYS[5],member) or '0')
 if active > now then return {'ADMITTED',tostring(now),tostring(active),'0'} end
 local alive=tonumber(redis.call('ZSCORE',KEYS[4],member) or '0') > now
 if alive then
  local rank=redis.call('ZRANK',KEYS[2],member)
  if rank then return {mode=='PAUSED' and 'PAUSED' or (now<starts and 'PREQUEUED' or 'WAITING'),tostring(now),'0',tostring(rank+1)} end
  rank=redis.call('ZRANK',KEYS[3],member)
  if rank then return {mode=='PAUSED' and 'PAUSED' or 'WAITING',tostring(now),'0',tostring(redis.call('ZCARD',KEYS[2])+rank+1)} end
 end
 return {'NOT_JOINED',tostring(now)}
end
-- Status is intentionally strictly read-only, including expiry handling.
if op == 'status' then return state() end
if op == 'leave' then remove(member);return {'NOT_JOINED',tostring(now)} end
if op == 'join' then
 if now >= ends then return {'SALES_ENDED',tostring(now)} end
 if now < prestart then return {'ADMISSION_NOT_OPEN',tostring(now)} end
 local current=state()
 if current[1] ~= 'NOT_JOINED' then return current end
 if not score or score<0 or score>4503599627370495 or score~=math.floor(score) then return {'INVALID'} end
 remove(member)
 if now < starts then redis.call('ZADD',KEYS[2],score,member)
 else
  local sequence=redis.call('INCR',KEYS[7])
  if sequence>4503599627370495 then return {'SEQUENCE_EXHAUSTED',tostring(now)} end
  redis.call('ZADD',KEYS[3],sequence,member)
 end
 redis.call('ZADD',KEYS[4],now+presence,member)
 redis.call('HSET',KEYS[6],member,now+heartbeat)
 touch();return state()
end
if op == 'heartbeat' then
 local current=state()
 if current[1]=='NOT_JOINED' or current[1]=='SALES_ENDED' then return current end
 local next=tonumber(redis.call('HGET',KEYS[6],member) or '0')
 if now < next then return current end
 if current[1]=='ADMITTED' then redis.call('ZADD',KEYS[5],now+lease,member)
 else redis.call('ZADD',KEYS[4],now+presence,member) end
 redis.call('HSET',KEYS[6],member,now+heartbeat)
 touch();return state()
end
if op ~= 'tick' then return {'INVALID'} end
-- Bounded cleanup; conservatively count uncollected expired active leases until next tick.
local expired=0
for _,index in ipairs({4,5}) do
 local dead=redis.call('ZRANGEBYSCORE',KEYS[index],'-inf',now,'LIMIT',0,batch)
 for _,id in ipairs(dead) do remove(id);expired=expired+1 end
end
if now < starts or now >= ends or mode=='PAUSED' or tonumber(redis.call('GET',KEYS[9]) or '0')>now then touch();return {'PAUSED',tostring(now),tostring(expired),'0'} end
local previous=tonumber(redis.call('HGET',KEYS[8],'time') or tostring(now))
local tokens=tonumber(redis.call('HGET',KEYS[8],'tokens') or '0')
tokens=math.min(rate*1000,tokens+math.max(0,math.min(3600000,now-previous))*rate)
local released=0
for i=1,batch do
 if tokens<1000 or redis.call('ZCARD',KEYS[5])>=capacity then break end
 local candidates=redis.call('ZRANGE',KEYS[2],0,0)
 local index=2
 if #candidates==0 then candidates=redis.call('ZRANGE',KEYS[3],0,0);index=3 end
 if #candidates==0 then break end
 local id=candidates[1]
 redis.call('ZREM',KEYS[index],id)
 if tonumber(redis.call('ZSCORE',KEYS[4],id) or '0')>now then
  redis.call('ZREM',KEYS[4],id)
  redis.call('ZADD',KEYS[5],now+lease,id)
  redis.call('HSET',KEYS[6],id,now+heartbeat)
  tokens=tokens-1000;released=released+1
 else remove(id) end
end
redis.call('HSET',KEYS[8],'time',math.max(now,previous),'tokens',tokens)
touch()
return {'OK',tostring(now),tostring(expired),tostring(released),tostring(redis.call('ZCARD',KEYS[2])+redis.call('ZCARD',KEYS[3])),tostring(redis.call('ZCARD',KEYS[5]))}
