# Gen 1 Recomp Integration

**Project:** PokeAchieve Tracker
**Purpose:** Track a [Pokemon Gen 1 recomp](https://github.com/acastango/pokemon-gen1-recomp-project) playthrough with the existing tracker — no emulator involved.

---

## How it works

The recomp is a native LÖVE/Lua reimplementation of Gen 1 — there is no Game Boy RAM for the tracker to read and no RetroArch to connect to. The bridge mod in [`recomp_mod/pokeachieve_bridge/`](recomp_mod/pokeachieve_bridge/) closes that gap from the other side:

1. It subscribes to the recomp's mod events (`pokemon.caught`, `battle.ended`, `save.loaded`, `world.stepped`, …) and, on every relevant change, rebuilds a snapshot of the **vanilla Red/Blue WRAM layout** from the live save — pokedex seen/caught bitflags at `0xD2F7`/`0xD30A`, party at `0xD163`/`0xD16B` (with Gen 1 *internal* species indexes, exactly as the real game stored them), badges at `0xD356`, champion at `0xD357`, Elite Four bytes at `0xD6E0`–`0xD6E3`.
2. A background thread serves that snapshot over **RetroArch's UDP network-command protocol** on `127.0.0.1:55355` — `GET_STATUS` answers `PLAYING game_boy,Pokemon Red,…`, `READ_CORE_MEMORY` answers synthesized WRAM bytes.

To the tracker, the recomp *is* RetroArch running Pokemon Red. No tracker code changes are needed: game detection, pokedex collection sync, party display, badge/Elite Four/champion achievements all work through the existing RetroArch connection path.

## Setup

1. Copy `recomp_mod/pokeachieve_bridge/` into the recomp project's `mods/` folder.
2. Launch the recomp (`love .` or the platform launcher) and make sure the mod is enabled in the mod manager.
3. Start the tracker (`python tracker_gui.py`) with its RetroArch connection left at the default `127.0.0.1:55355`.
4. Load or start a save in the recomp. The tracker detects "Pokemon Red" and begins polling, exactly as it would against RetroArch.

The tracker shows "RetroArch Closed, waiting on RetroArch launch" until the recomp is running with a save loaded — the mod answers `CONTENTLESS` on the title screen/launcher, so the tracker keeps waiting quietly until you're in the world.

### Running RetroArch and the recomp at the same time

Both want UDP 55355. Change the port in the mod's options (UDP PORT → 55356 or 55357) and set the same port in the tracker under RetroArch connection settings.

## What is and isn't tracked

Works through the bridge:

- Pokedex seen/caught (live collection sync, 151 species)
- Party (species, level, HP, status; Gen 1 internal→national conversion is handled by the tracker as usual)
- Badge, Elite Four, Champion, legendary and pokedex-completion achievements

Limitations:

- Wild-encounter OCR/sprite detection is a separate OBS-based pipeline; point it at a capture of the recomp window if you use hunts. Memory-based tracking does not depend on it.
- Mod-added species with no national dex number 1–151 have no vanilla byte to map to and appear as empty party slots to the tracker.
- Party move bytes are served as zeros (the recomp stores moves by name; the tracker only displays them, so nothing breaks).

## Verification

The bridge ships with tests, all runnable from the recomp project root:

```sh
python3 tools/modkit.py validate mods/pokeachieve_bridge   # loader check
python3 tools/modkit.py lint mods/pokeachieve_bridge
luajit mods/pokeachieve_bridge/tests/pokeachieve_bridge_test.lua   # 22 byte-level checks
```

The integration was also verified end-to-end: the tracker's own `RetroArchClient.get_current_game()` and `PokemonMemoryReader.read_party()` were run unmodified against the mod's live UDP server and returned correct results ("Pokemon Red", correct dex flags, correct party species/levels).

---

*Last Updated: 2026-08-01*
