if not ready() then
  if redis.call('EXISTS', key('init-lock')) == 1 then return {'INITIALIZING'} end
  return {'NO_MODEL'}
end
local id, status, version, maxlen = ARGV[1], ARGV[2], ARGV[3], tonumber(ARGV[4])
if not formal(status .. '|' .. version) or not maxlen or maxlen <= 0 then return redis.error_reply('invalid projection') end
if not healthy() or not validseat(id) then invalidate(); return {'ERROR'} end
local old, oldversion = formal(redis.call('HGET', key('formal'), id))
if not greater(version, oldversion) then return {'STALE_OR_DUPLICATE'} end
local z = redis.call('HGET', key('seat-zone'), id)
local h = redis.call('HGET', key('holds'), id)
summarychange(z, publicstatus(old,h), publicstatus(status,h))
redis.call('HSET', key('formal'), id, status .. '|' .. version)
-- Accepted formal versions matter to the owner even when public HELD is unchanged.
change(z,id,maxlen)
return {'APPLIED'}
