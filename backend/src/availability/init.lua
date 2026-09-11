local token, generation = ARGV[1], ARGV[2]
if redis.call('GET', key('init-lock')) ~= token then return {'STALE_INIT'} end
local rows = cjson.decode(ARGV[3])
local seen, zoneSeen, zones = {}, {}, {}
-- Parse everything and inspect every original Hold before deleting derived keys.
for _, r in ipairs(rows) do
  if type(r) ~= 'table' or #r ~= 4 or type(r[1]) ~= 'string' or type(r[4]) ~= 'string' or seen[r[1]] or not formal(r[2] .. '|' .. r[3]) then return redis.error_reply('invalid init payload') end
  seen[r[1]] = true
  if not zoneSeen[r[4]] then zoneSeen[r[4]] = true; zones[#zones+1] = r[4] end
  if not compatible(holdkey(r[1]), 'string') then return redis.error_reply('invalid original hold type') end
  local raw = redis.call('GET', holdkey(r[1]))
  if raw and not rawhold(raw) then return redis.error_reply('invalid original hold') end
end
if not compatible(key('zones'), 'list') then return redis.error_reply('invalid old zones') end
for _, z in ipairs(redis.call('LRANGE', key('zones'), 0, -1)) do
  redis.call('DEL', zonekey(z,'seats'), zonekey(z,'summary'), zonekey(z,'changes'))
end
for _, suffix in ipairs({'meta','zones','seat-zone','formal','holds','hold-expiry'}) do redis.call('DEL', key(suffix)) end
for _, z in ipairs(zones) do
  redis.call('DEL', zonekey(z,'seats'), zonekey(z,'summary'), zonekey(z,'changes'))
  redis.call('RPUSH', key('zones'), z)
  redis.call('HSET', zonekey(z,'summary'), 'total',0,'available',0,'held',0,'sold',0)
  redis.call('XADD', zonekey(z,'changes'), '*', 'kind','baseline')
end
local now = nowms()
for _, r in ipairs(rows) do
  local id, status, version, z = r[1], r[2], r[3], r[4]
  redis.call('HSET', key('seat-zone'), id, z)
  redis.call('HSET', key('formal'), id, status .. '|' .. version)
  redis.call('SADD', zonekey(z,'seats'), id)
  local raw = redis.call('GET', holdkey(id))
  local ttl = redis.call('PTTL', holdkey(id))
  if raw and ttl > 0 then
    redis.call('HSET', key('holds'), id, raw .. '|' .. string.format('%.0f', now + ttl))
    redis.call('ZADD', key('hold-expiry'), now + ttl, id)
  else raw = nil end
  redis.call('HINCRBY', zonekey(z,'summary'), 'total', 1)
  redis.call('HINCRBY', zonekey(z,'summary'), string.lower(publicstatus(status,raw)), 1)
end
redis.call('HSET', key('meta'), 'generation',generation, 'ready','1')
redis.call('DEL', key('init-lock'))
return {'READY', generation}
