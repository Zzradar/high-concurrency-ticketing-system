-- Shared Phase16 primitives. All keys use the existing session hash tag.
local prefix = KEYS[1]
local function key(suffix) return prefix .. ':' .. suffix end
local function zonekey(zone, suffix) return key('zone:' .. zone .. ':' .. suffix) end
local function typename(k) return redis.call('TYPE', k).ok end
local function compatible(k, expected)
  local t = typename(k)
  return t == 'none' or t == expected
end
local function nowms()
  local t = redis.call('TIME')
  return tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end
local function decimal(s)
  return type(s) == 'string' and (s == '0' or string.match(s, '^[1-9][0-9]*$'))
end
local function greater(a, b)
  if #a ~= #b then return #a > #b end
  return a > b
end
local function formal(s)
  if type(s) ~= 'string' then return nil end
  local status, version = string.match(s, '^([A-Z]+)|([0-9]+)$')
  if (status ~= 'AVAILABLE' and status ~= 'HELD' and status ~= 'SOLD') or not decimal(version) then return nil end
  return status, version
end
local function rawhold(s)
  if type(s) ~= 'string' then return nil end
  local owner, revision = string.match(s, '^([^|]+)|([0-9]+)$')
  if not owner or not decimal(revision) then return nil end
  return owner, revision
end
local function hold(s)
  if type(s) ~= 'string' then return nil end
  local raw, expiry = string.match(s, '^(.*)|([0-9]+)$')
  local owner, revision = rawhold(raw)
  if not owner then return nil end
  return owner, revision, tonumber(expiry)
end
local function holdkey(id)
  return string.gsub(prefix, 'seat%-availability:', 'seat-hold:', 1) .. ':' .. id
end
local function ready()
  return compatible(key('meta'), 'hash') and redis.call('HGET', key('meta'), 'ready') == '1'
end
local function invalidate()
  redis.call('DEL', key('meta'))
end
-- Full type/shape validation happens before any business Hold writes. Invalid
-- derived data is discarded via generation rebuild, never allowed to fail late.
local function healthy()
  if not ready() then return false end
  for suffix, t in pairs({zones='list', ['seat-zone']='hash', formal='hash', holds='hash', ['hold-expiry']='zset'}) do
    if not compatible(key(suffix), t) then return false end
  end
  for suffix, t in pairs({zones='list', ['seat-zone']='hash', formal='hash'}) do
    if typename(key(suffix)) ~= t then return false end
  end
  local zones = redis.call('LRANGE', key('zones'), 0, -1)
  for _, z in ipairs(zones) do
    if typename(zonekey(z, 'seats')) ~= 'set' or typename(zonekey(z, 'summary')) ~= 'hash' or typename(zonekey(z, 'changes')) ~= 'stream' then return false end
    local count = redis.call('SCARD',zonekey(z,'seats'))
    local sum = 0
    for _, name in ipairs({'total','available','held','sold'}) do
      local value = redis.call('HGET', zonekey(z, 'summary'), name)
      if not decimal(value) or #value > 10 or tonumber(value) > count then return false end
      if name == 'total' then
        if tonumber(value) ~= count then return false end
      else sum = sum + tonumber(value) end
    end
    if sum ~= count then return false end
  end
  return true
end
local function validseat(id)
  local z = redis.call('HGET', key('seat-zone'), id)
  if not z or not formal(redis.call('HGET', key('formal'), id)) then return false end
  local h = redis.call('HGET', key('holds'), id)
  if h and not hold(h) then return false end
  return redis.call('SISMEMBER', zonekey(z, 'seats'), id) == 1
end
local function publicstatus(status, h)
  if status ~= 'AVAILABLE' then return status end
  return h and 'HELD' or 'AVAILABLE'
end
local function summarychange(z, old, new)
  if old == new then return end
  redis.call('HINCRBY', zonekey(z, 'summary'), string.lower(old), -1)
  redis.call('HINCRBY', zonekey(z, 'summary'), string.lower(new), 1)
end
local function change(z, id, maxlen)
  redis.call('XADD', zonekey(z, 'changes'), 'MAXLEN', '~', maxlen, '*', 'kind','change','seatId',id)
end
local function synchold(id, maxlen)
  local z = redis.call('HGET', key('seat-zone'), id)
  local status = formal(redis.call('HGET', key('formal'), id))
  local previous = redis.call('HGET', key('holds'), id)
  local oldowner = hold(previous)
  local raw = redis.call('GET', holdkey(id))
  local owner = rawhold(raw)
  local ttl = redis.call('PTTL', holdkey(id))
  if ttl <= 0 then owner = nil end
  if owner then
    local expiry = nowms() + ttl
    redis.call('HSET', key('holds'), id, raw .. '|' .. string.format('%.0f', expiry))
    redis.call('ZADD', key('hold-expiry'), expiry, id)
  else
    redis.call('HDEL', key('holds'), id)
    redis.call('ZREM', key('hold-expiry'), id)
  end
  summarychange(z, publicstatus(status, oldowner), publicstatus(status, owner))
  if status == 'AVAILABLE' and oldowner ~= owner then change(z, id, maxlen) end
end
