-- UDP server thread for the PokeAchieve bridge.  Speaks just enough of
-- RetroArch's network-command protocol for the PokeAchieve tracker:
--
--   GET_STATUS                   -> GET_STATUS PLAYING game_boy,<game>,crc32=0
--   READ_CORE_MEMORY <addr> <n>  -> READ_CORE_MEMORY <addr> aa bb cc ...
--   VERSION                      -> 1.16.0
--
-- It never touches game state: the main thread pushes immutable snapshot
-- strings over a channel and this loop answers reads from the latest one.

local generation, port = ...

require("love.timer")
local socket = require("socket")

local stateChannel = love.thread.getChannel("pokeachieve_bridge.state")
local genChannel = love.thread.getChannel("pokeachieve_bridge.gen")

local function retired()
  return genChannel:peek() ~= generation
end

-- A hot reload starts a replacement thread while this one may still hold
-- the port for up to one receive timeout; retry the bind briefly.
local udp
for _ = 1, 40 do
  if retired() then return end
  udp = socket.udp()
  udp:settimeout(0.25)
  local ok = udp:setsockname("127.0.0.1", port)
  if ok then break end
  udp:close()
  udp = nil
  love.timer.sleep(0.25)
end
if not udp then return end

local latest = nil

-- longest read the tracker issues is 1200 bytes; keep the reply datagram
-- inside its 4096-byte receive buffer
local MAX_READ = 1300

local function handle(line, ip, fromPort)
  local reply
  if line == "GET_STATUS" then
    if latest and latest.game then
      reply = ("GET_STATUS PLAYING game_boy,%s,crc32=0"):format(latest.game)
    else
      reply = "GET_STATUS CONTENTLESS"
    end
  elseif line == "VERSION" then
    reply = "1.16.0"
  else
    local addrText, lenText = line:match("^READ_CORE_MEMORY%s+(%S+)%s*(%S*)")
    if not addrText then return end
    local addr = tonumber(addrText)
    if not addr then addr = tonumber(addrText, 16) end
    local length = math.max(1, math.min(MAX_READ, tonumber(lenText) or 1))
    if not addr or not latest or not latest.game then
      reply = ("READ_CORE_MEMORY %s -1"):format(addrText)
    else
      local base, data = latest.base, latest.data
      local bytes = {}
      for i = 0, length - 1 do
        local offset = addr + i - base + 1
        local value = 0
        if offset >= 1 and offset <= #data then
          value = data:byte(offset)
        end
        bytes[#bytes + 1] = ("%02x"):format(value)
      end
      reply = ("READ_CORE_MEMORY %s %s"):format(addrText, table.concat(bytes, " "))
    end
  end
  if reply then
    udp:sendto(reply .. "\n", ip, fromPort)
  end
end

while not retired() do
  local message = stateChannel:pop()
  while message do
    latest = message
    if latest.game == false then latest = { game = nil } end
    message = stateChannel:pop()
  end

  local data, ip, fromPort = udp:receivefrom()
  if data and ip then
    for line in data:gmatch("[^\r\n]+") do
      handle(line, ip, fromPort)
    end
  end
end

udp:close()
