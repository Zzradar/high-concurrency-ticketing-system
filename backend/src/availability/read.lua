if not healthy() then invalidate(); return {'REBUILD'} end
local z, generation, since = ARGV[1], ARGV[2], ARGV[3]
local limit = tonumber(ARGV[4])
if not limit or limit <= 0 then return redis.error_reply('invalid delta limit') end
if redis.call('EXISTS', zonekey(z,'seats')) == 0 then return {'ZONE_NOT_FOUND'} end
local current = redis.call('HGET',key('meta'),'generation')
local stream = zonekey(z,'changes')
local function cursorless(a,b)
  local am,as = string.match(a,'^([0-9]+)%-([0-9]+)$')
  local bm,bs = string.match(b,'^([0-9]+)%-([0-9]+)$')
  if am ~= bm then return greater(bm,am) end
  return greater(bs,as)
end
local mode, reset, more, reason = 'snapshot','0','0',''
local cursor, ids, seen = since, {}, {}
if generation ~= '' then
  local first = redis.call('XRANGE',stream,'-','+','COUNT',1)
  if generation ~= current then reset='1'; reason='generation'
  elseif #first == 0 then return {'REBUILD'}
  elseif cursorless(since,first[1][1]) then reset='1'; reason='trim'
  else
    mode = 'delta'
    local events = redis.call('XRANGE',stream,'(' .. since,'+','COUNT',limit+1)
    if #events > limit then more='1' end
    for index=1,math.min(#events,limit) do
      local event = events[index]
      cursor = event[1]
      local kind, id
      for j=1,#event[2],2 do
        if event[2][j]=='kind' then kind=event[2][j+1] end
        if event[2][j]=='seatId' then id=event[2][j+1] end
      end
      if kind=='change' and id and not seen[id] then ids[#ids+1]=id; seen[id]=true end
    end
  end
end
if mode=='snapshot' then
  ids = redis.call('SMEMBERS',zonekey(z,'seats'))
  table.sort(ids)
  cursor = redis.call('XREVRANGE',stream,'+','-','COUNT',1)[1][1]
end
local zones = redis.call('LRANGE',key('zones'),0,-1)
local result = {'OK',mode,current,cursor,reset,more,reason,tostring(#zones)}
for _, zone in ipairs(zones) do
  result[#result+1]=zone
  for _, name in ipairs({'total','available','held','sold'}) do result[#result+1]=redis.call('HGET',zonekey(zone,'summary'),name) end
end
result[#result+1]=tostring(#ids)
local now = nowms()
for _, id in ipairs(ids) do
  if not validseat(id) or redis.call('HGET',key('seat-zone'),id) ~= z then invalidate(); return {'REBUILD'} end
  local status = formal(redis.call('HGET',key('formal'),id))
  local owner, revision, expiry = hold(redis.call('HGET',key('holds'),id))
  if expiry and expiry <= now then owner=nil end
  result[#result+1]=id; result[#result+1]=status; result[#result+1]=owner or ''
end
return result
