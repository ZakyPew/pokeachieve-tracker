# PokeAchieve Tracker Bridge

Makes the [PokeAchieve tracker](https://github.com/ZakyPew/pokeachieve-tracker) work with the Pokemon Gen 1 recomp by pretending to be RetroArch: it serves the recomp's live save state over RetroArch's UDP network-command protocol, synthesized into the vanilla Red/Blue WRAM layout the tracker already reads. Persona: the player who wants their recomp playthrough on their PokeAchieve profile without running an emulator.

Try it:

```sh
# from the recomp project root, with this folder copied into mods/
python3 tools/modkit.py validate mods/pokeachieve_bridge
python3 tools/modkit.py lint mods/pokeachieve_bridge
love .
```

Then start the tracker (`python tracker_gui.py`) — it connects to `127.0.0.1:55355` exactly as it would to RetroArch, detects "Pokemon Red", and pokedex/party/badge/Elite Four tracking works unchanged.

## What it serves

| Region | Vanilla address | Source in the recomp |
| --- | --- | --- |
| Pokedex seen flags | `0xD2F7` | `save.pokedex.seen` |
| Pokedex caught flags | `0xD30A` | `save.pokedex.owned` |
| Party count / species / mons | `0xD163` / `0xD164` / `0xD16B` | `save.party` (species, level, HP, status) |
| Badges | `0xD356` | `save.inventory` badge items |
| Champion | `0xD357` | `EVENT_BEAT_CHAMPION_RIVAL` |
| Elite Four | `0xD6E0`-`0xD6E3` | `EVENT_BEAT_*` room flags |

Party species bytes use the Gen 1 internal order, exactly as vanilla stored them — the tracker converts back to national dex numbers itself.

## Options

- **UDP PORT** — 55355 (default), 55356, or 55357. Change it if RetroArch runs at the same time, and set the same port in the tracker's RetroArch connection settings.
