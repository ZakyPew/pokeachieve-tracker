-- Standalone: luajit mods/pokeachieve_bridge/tests/pokeachieve_bridge_test.lua
-- (run from the recomp project root with the mod copied into mods/).
-- Exercises the snapshot builder against the ROM-free fixture dataset:
-- FIXMON_A/B/C carry dex numbers 1/2/3, which map to Gen 1 internal
-- species 153/9/154.
package.path = "./?.lua;./?/init.lua;" .. package.path

local T = require("tests.modkit")

local run = T.sdk.loadMod("mods/pokeachieve_bridge")
T.eq(#run.errors, 0, "loads clean (" .. tostring(run.errors[1]) .. ")")

local exports = run.loader.exports.pokeachieve_bridge
T.check(type(exports.buildImage) == "function", "buildImage is exported")
T.check(type(exports.gameLabel) == "function", "gameLabel is exported")

local save = {
  version = "red",
  pokedex = {
    seen = { FIXMON_A = true, FIXMON_B = true },
    owned = { FIXMON_B = true },
  },
  party = {
    { species = "FIXMON_A", level = 12, hp = 30, stats = { hp = 31 }, status = "PAR" },
  },
  inventory = { BOULDERBADGE = 1, CASCADEBADGE = 1 },
  flags = { EVENT_BEAT_LANCE = true, EVENT_BEAT_CHAMPION_RIVAL = true },
}

local base, image = exports.buildImage(save)
T.eq(base, 0xD158, "image is anchored at 0xD158")
T.eq(#image, 0xD700 - 0xD158, "image spans through 0xD6FF")

local function byteAt(addr) return image:byte(addr - base + 1) end

-- pokedex bitflags: dex 1 -> bit 0, dex 2 -> bit 1 of the first byte
T.eq(byteAt(0xD2F7), 3, "seen flags set bits 0 and 1")
T.eq(byteAt(0xD30A), 2, "owned flags set bit 1 only")

-- party: vanilla stores the Gen 1 internal index, not the dex number
T.eq(byteAt(0xD163), 1, "party count")
T.eq(byteAt(0xD164), 153, "species list byte is internal id (dex 1 -> 153)")
T.eq(byteAt(0xD165), 0xFF, "species list is terminated")
T.eq(byteAt(0xD16B), 153, "slot species byte is internal id")
T.eq(byteAt(0xD16B + 0x03), 12, "slot level at offset 3")
T.eq(byteAt(0xD16B + 0x04), 0x40, "PAR maps to status bit 6")
T.eq(byteAt(0xD16B + 0x02), 30, "current HP low byte")
T.eq(byteAt(0xD16B + 0x21), 12, "party level at offset 0x21")

-- progress bytes
T.eq(byteAt(0xD356), 3, "two badges set bits 0 and 1")
T.eq(byteAt(0xD357), 1, "champion flag reads as 1")
T.eq(byteAt(0xD6E0), 0, "Lorelei byte still 0")
T.eq(byteAt(0xD6E3), 1, "Lance byte reads as 1")

T.eq(exports.gameLabel(save), "Pokemon Red", "red save labels as Pokemon Red")
T.eq(exports.gameLabel({ version = "blue" }), "Pokemon Blue",
  "blue save labels as Pokemon Blue")

-- an empty save is a legal state, not a crash
local _, empty = exports.buildImage({})
T.eq(empty:byte(0xD163 - base + 1), 0, "empty save has zero party count")

run.release()
T.finish("pokeachieve_bridge")
