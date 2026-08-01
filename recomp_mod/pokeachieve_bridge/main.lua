-- PokeAchieve Tracker Bridge.  The tracker only knows how to talk to
-- RetroArch: it sends GET_STATUS / READ_CORE_MEMORY datagrams to UDP
-- 55355 and expects Game Boy WRAM back.  The recomp has no WRAM, so this
-- mod rebuilds the handful of vanilla Red/Blue regions the tracker reads
-- (pokedex flags, party, badges, Elite Four events) from the live save and
-- serves them from a background thread that speaks RetroArch's protocol.
--
-- Everything it reads comes through the public mod API; the UDP server
-- never touches game state directly -- it only ever sees an immutable
-- snapshot string pushed over a channel.

-- The synthesized window of WRAM: 0xD158 .. 0xD6FF covers every address
-- the tracker asks for.  Reads outside it answer zero.
local BASE = 0xD158
local SIZE = 0xD700 - BASE

-- vanilla WRAM anchors (pret/pokered wram.asm)
local ADDR = {
  partyCount = 0xD163,   -- wPartyCount
  partySpecies = 0xD164, -- wPartySpecies list, 0xFF-terminated
  partyMons = 0xD16B,    -- wPartyMons, 44 bytes per mon
  dexSeen = 0xD2F7,      -- wPokedexSeen, 19 bytes of bitflags
  dexOwned = 0xD30A,     -- wPokedexOwned, 19 bytes of bitflags
  badges = 0xD356,       -- wObtainedBadges
  champion = 0xD357,     -- champion event byte the tracker tests with & 1
  eliteFour = 0xD6E0,    -- four bytes: Lorelei, Bruno, Agatha, Lance
}
local PARTY_STRIDE = 44

-- National dex number -> Gen 1 internal species index (the byte vanilla
-- stores in wPartyMons; pret/pokered data/pokemon/dex_order.asm inverted).
local NATIONAL_TO_INTERNAL = {
  [1] = 153, [2] = 9, [3] = 154, [4] = 176, [5] = 178, [6] = 180, [7] = 177, [8] = 179,
  [9] = 28, [10] = 123, [11] = 124, [12] = 125, [13] = 112, [14] = 113, [15] = 114, [16] = 36,
  [17] = 150, [18] = 151, [19] = 165, [20] = 166, [21] = 5, [22] = 35, [23] = 108, [24] = 45,
  [25] = 84, [26] = 85, [27] = 96, [28] = 97, [29] = 15, [30] = 168, [31] = 16, [32] = 3,
  [33] = 167, [34] = 7, [35] = 4, [36] = 142, [37] = 82, [38] = 83, [39] = 100, [40] = 101,
  [41] = 107, [42] = 130, [43] = 185, [44] = 186, [45] = 187, [46] = 109, [47] = 46, [48] = 65,
  [49] = 119, [50] = 59, [51] = 118, [52] = 77, [53] = 144, [54] = 47, [55] = 128, [56] = 57,
  [57] = 117, [58] = 33, [59] = 20, [60] = 71, [61] = 110, [62] = 111, [63] = 148, [64] = 38,
  [65] = 149, [66] = 106, [67] = 41, [68] = 126, [69] = 188, [70] = 189, [71] = 190, [72] = 24,
  [73] = 155, [74] = 169, [75] = 39, [76] = 49, [77] = 163, [78] = 164, [79] = 37, [80] = 8,
  [81] = 173, [82] = 54, [83] = 64, [84] = 70, [85] = 116, [86] = 58, [87] = 120, [88] = 13,
  [89] = 136, [90] = 23, [91] = 139, [92] = 25, [93] = 147, [94] = 14, [95] = 34, [96] = 48,
  [97] = 129, [98] = 78, [99] = 138, [100] = 6, [101] = 141, [102] = 12, [103] = 10, [104] = 17,
  [105] = 145, [106] = 43, [107] = 44, [108] = 11, [109] = 55, [110] = 143, [111] = 18, [112] = 1,
  [113] = 40, [114] = 30, [115] = 2, [116] = 92, [117] = 93, [118] = 157, [119] = 158, [120] = 27,
  [121] = 152, [122] = 42, [123] = 26, [124] = 72, [125] = 53, [126] = 51, [127] = 29, [128] = 60,
  [129] = 133, [130] = 22, [131] = 19, [132] = 76, [133] = 102, [134] = 105, [135] = 104, [136] = 103,
  [137] = 170, [138] = 98, [139] = 99, [140] = 90, [141] = 91, [142] = 171, [143] = 132, [144] = 74,
  [145] = 75, [146] = 73, [147] = 88, [148] = 89, [149] = 66, [150] = 131, [151] = 21,
}

-- wObtainedBadges bit order; badges live in save.inventory keyed by id
local BADGE_ORDER = {
  "BOULDERBADGE", "CASCADEBADGE", "THUNDERBADGE", "RAINBOWBADGE",
  "SOULBADGE", "MARSHBADGE", "VOLCANOBADGE", "EARTHBADGE",
}

-- gen 1 status byte (wPartyMon1Status): sleep counter in bits 0-2
local STATUS_BITS = { SLP = 0x04, PSN = 0x08, BRN = 0x10, FRZ = 0x20, PAR = 0x40 }

local ELITE_FOUR_FLAGS = {
  "EVENT_BEAT_LORELEIS_ROOM_TRAINER_0",
  "EVENT_BEAT_BRUNOS_ROOM_TRAINER_0",
  "EVENT_BEAT_AGATHAS_ROOM_TRAINER_0",
  "EVENT_BEAT_LANCE",
}

local unpack = unpack or table.unpack

local STATE_CHANNEL = "pokeachieve_bridge.state"
local GEN_CHANNEL = "pokeachieve_bridge.gen"

return function(mod)
  mod.options:define({
    { key = "port", label = "UDP PORT", type = "choice", default = "55355",
      choices = { { "55355", "55355" }, { "55356", "55356" }, { "55357", "55357" } } },
  })

  -- ------- snapshot building (main thread; sees live save, produces a string)

  local buffer = {}

  local function poke(addr, value)
    local index = addr - BASE + 1
    if index >= 1 and index <= SIZE then
      buffer[index] = value % 256
    end
  end

  local function pokeBit(baseAddr, number)
    local index = number - 1
    local addr = baseAddr + math.floor(index / 8)
    local bit = index % 8
    local current = buffer[addr - BASE + 1] or 0
    local mask = 2 ^ bit
    if current % (mask * 2) < mask then
      poke(addr, current + mask)
    end
  end

  local function dexNumberOf(speciesId)
    local def = speciesId and mod.content.pokemon:get(speciesId)
    local dex = def and tonumber(def.dex)
    return (dex and dex >= 1 and dex <= 151) and dex or nil
  end

  -- Rebuild the synthesized WRAM window from a save table.  Exported (and
  -- returned) so the headless test can assert bytes without a socket.
  local function buildImage(save)
    for i = 1, SIZE do buffer[i] = 0 end

    local pokedex = save.pokedex or {}
    for speciesId in pairs(pokedex.seen or {}) do
      local dex = dexNumberOf(speciesId)
      if dex then pokeBit(ADDR.dexSeen, dex) end
    end
    for speciesId in pairs(pokedex.owned or {}) do
      local dex = dexNumberOf(speciesId)
      if dex then pokeBit(ADDR.dexOwned, dex) end
    end

    local party = save.party or {}
    local count = math.min(#party, 6)
    poke(ADDR.partyCount, count)
    poke(ADDR.partySpecies + count, 0xFF)
    for i = 1, count do
      local mon = party[i]
      local dex = dexNumberOf(mon.species)
      local internal = (dex and NATIONAL_TO_INTERNAL[dex]) or 0
      poke(ADDR.partySpecies + i - 1, internal)

      local slot = ADDR.partyMons + (i - 1) * PARTY_STRIDE
      local level = math.max(0, math.min(255, tonumber(mon.level) or 0))
      local hp = math.max(0, math.min(65535, tonumber(mon.hp) or 0))
      local maxHp = math.max(0, math.min(65535,
        tonumber(mon.stats and mon.stats.hp) or 0))
      poke(slot, internal)
      poke(slot + 0x01, math.floor(hp / 256))
      poke(slot + 0x02, hp % 256)
      poke(slot + 0x03, level)          -- box level; tracker reads this one
      poke(slot + 0x04, STATUS_BITS[mon.status] or 0)
      poke(slot + 0x21, level)          -- party level
      poke(slot + 0x22, math.floor(maxHp / 256))
      poke(slot + 0x23, maxHp % 256)
    end

    local inventory = save.inventory or {}
    local badges = 0
    for bit, badgeId in ipairs(BADGE_ORDER) do
      if inventory[badgeId] then badges = badges + 2 ^ (bit - 1) end
    end
    poke(ADDR.badges, badges)

    local flags = save.flags or {}
    poke(ADDR.champion, flags.EVENT_BEAT_CHAMPION_RIVAL and 1 or 0)
    for i, flagName in ipairs(ELITE_FOUR_FLAGS) do
      poke(ADDR.eliteFour + i - 1, flags[flagName] and 1 or 0)
    end

    local parts = {}
    for i = 1, SIZE, 512 do
      parts[#parts + 1] = string.char(unpack(buffer, i, math.min(i + 511, SIZE)))
    end
    return BASE, table.concat(parts)
  end

  local function gameLabel(save)
    return save.version == "blue" and "Pokemon Blue" or "Pokemon Red"
  end

  mod.exports.buildImage = buildImage
  mod.exports.gameLabel = gameLabel

  -- ------- publishing (main thread -> server thread)

  -- Headless runs (modkit validate, tests) have no love.thread; the mod
  -- still loads and exports, it just never opens a socket.
  local threaded = love and love.thread and love.filesystem and true or false
  if not threaded then
    mod.log:info("no threading available; UDP server disabled (headless run)")
  end

  local liveGame = nil
  local lastSave = nil

  local function currentSave()
    local save = (liveGame and liveGame.save) or lastSave
    if type(save) ~= "table" then return nil end
    -- a save table exists before the player is in the world on some paths;
    -- treat one with no player as "nothing loaded"
    if type(save.pokedex) ~= "table" and type(save.party) ~= "table" then
      return nil
    end
    return save
  end

  local function publish()
    if not threaded then return end
    local channel = love.thread.getChannel(STATE_CHANNEL)
    local save = currentSave()
    if not save then
      channel:clear()
      channel:push({ game = false })
      return
    end
    local ok, base, image = pcall(buildImage, save)
    if not ok then
      mod.log:warn("snapshot build failed: %s", tostring(base))
      return
    end
    channel:clear()
    channel:push({ game = gameLabel(save), base = base, data = image })
  end

  -- ------- the server thread

  if threaded then
    local source = mod:read("server_thread.lua")
    if type(source) ~= "string" or #source == 0 then
      mod.log:error("server_thread.lua missing; UDP server disabled")
    else
      -- generation counter lets a hot-reloaded instance retire the old
      -- thread: the running loop sees a newer number and exits
      local genChannel = love.thread.getChannel(GEN_CHANNEL)
      local generation = (genChannel:peek() or 0) + 1
      genChannel:clear()
      genChannel:push(generation)

      local port = tonumber(mod.options:get("port")) or 55355
      local thread = love.thread.newThread(source)
      thread:start(generation, port)
      mod.log:info("UDP bridge listening on 127.0.0.1:%d (RetroArch protocol)", port)
    end
  end

  -- ------- keeping the snapshot fresh

  mod.events:on("game.ready", function(payload)
    liveGame = payload and payload.game or liveGame
    publish()
  end)
  mod.events:on("save.loaded", function(payload)
    lastSave = payload and payload.save or lastSave
    publish()
  end)

  local REFRESH_EVENTS = {
    "save.created", "save.writing",
    "pokemon.caught", "pokemon.received", "pokemon.evolved",
    "pokemon.level_up", "trade.completed",
    "battle.started", "battle.turn_ended", "battle.ended",
    "flag.changed", "map.entered", "world.stepped",
    "screen.popped",
  }
  for _, name in ipairs(REFRESH_EVENTS) do
    mod.events:on(name, publish)
  end
end
