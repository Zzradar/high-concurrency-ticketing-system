if not healthy() then invalidate(); return {'REBUILD'} end
local limit, maxlen = tonumber(ARGV[1]), tonumber(ARGV[2])
if not limit or limit <= 0 or not maxlen or maxlen <= 0 then return redis.error_reply('invalid cleanup config') end
local now = nowms()
local ids = redis.call('ZRANGEBYSCORE', key('hold-expiry'), '-inf', now, 'LIMIT', 0, limit)
for _, id in ipairs(ids) do
  if not validseat(id) or not compatible(holdkey(id),'string') then invalidate(); return {'REBUILD'} end
  local raw = redis.call('GET', holdkey(id))
  if raw and not rawhold(raw) then invalidate(); return {'REBUILD'} end
end
local count = 0
for _, id in ipairs(ids) do
  local owner, revision, expiry = hold(redis.call('HGET', key('holds'), id))
  if owner and expiry <= now then
    local raw = redis.call('GET',holdkey(id))
    if raw == owner .. '|' .. revision then redis.call('DEL',holdkey(id)) end
    -- If a newer raw Hold exists, synchronize it rather than erasing its owner.
    synchold(id,maxlen)
    count = count + 1
  elseif owner then
    redis.call('ZADD',key('hold-expiry'),expiry,id)
  else
    redis.call('ZREM',key('hold-expiry'),id)
  end
end
return {'OK', tostring(count), tostring(redis.call('ZCOUNT',key('hold-expiry'),'-inf',now))}
