-- Prefix supplied separately from the original KEYS and ARGV contract.
local modelReady = ready()
local affected = {}
if modelReady then
  modelReady = healthy()
  if modelReady then
    for _, original in ipairs(originalKeys) do
      local id = string.sub(original, #holdkey('') + 1)
      if not validseat(id) then modelReady=false; break end
      affected[#affected+1]=id
    end
  end
  if not modelReady then invalidate() end
end
-- Preflight original types/revisions even for delete operations before any DEL.
for _, original in ipairs(originalKeys) do
  if not compatible(original,'string') then return redis.error_reply('invalid original hold type') end
  local raw=redis.call('GET',original)
  if raw and not rawhold(raw) then return redis.error_reply('malformed seat hold revision') end
end
local KEYS = originalKeys
local result = originalOperation()
if modelReady then
  for _, id in ipairs(affected) do synchold(id,streamMaxlen) end
end
return result
