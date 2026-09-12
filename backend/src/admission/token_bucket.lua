-- Two buckets in one event hash slot; integer milli-token accounting.
-- ARGV: account capacity/rate, event capacity/rate, cost (whole tokens).
local ac,ar,ec,er,cost=tonumber(ARGV[1]),tonumber(ARGV[2]),tonumber(ARGV[3]),tonumber(ARGV[4]),tonumber(ARGV[5])
for _,n in ipairs({ac or 0,ar or 0,ec or 0,er or 0,cost or 0}) do
 if n<1 or n>1000000 or n~=math.floor(n) then return {'INVALID'} end
end
if cost>ac or cost>ec then return {'INVALID'} end
local time=redis.call('TIME');local now=tonumber(time[1])*1000+math.floor(tonumber(time[2])/1000)
local function refill(key,capacity,rate)
 local last=tonumber(redis.call('HGET',key,'time') or tostring(now))
 local tokens=tonumber(redis.call('HGET',key,'tokens') or tostring(capacity*1000))
 local elapsed=math.max(0,math.min(3600000,now-last))
 return math.min(capacity*1000,math.max(0,tokens)+elapsed*rate)
end
local a,e=refill(KEYS[1],ac,ar),refill(KEYS[2],ec,er)
local need=cost*1000;local retry=0;local scope='NONE'
if a<need then retry=math.ceil((need-a)/ar);scope='ACCOUNT' end
if e<need then retry=math.max(retry,math.ceil((need-e)/er));scope=scope=='ACCOUNT' and 'BOTH' or 'EVENT' end
if retry==0 then a=a-need;e=e-need end
-- A rejection may commit refill/clock normalization but never debit either bucket.
redis.call('HSET',KEYS[1],'tokens',a,'time',now)
redis.call('HSET',KEYS[2],'tokens',e,'time',now)
redis.call('PEXPIRE',KEYS[1],math.min(86400000,math.ceil(ac*1000/ar)+60000))
redis.call('PEXPIRE',KEYS[2],math.min(86400000,math.ceil(ec*1000/er)+60000))
return {retry==0 and 'ALLOWED' or 'RATE_LIMITED',scope,tostring(math.max(0,retry)),tostring(now)}
