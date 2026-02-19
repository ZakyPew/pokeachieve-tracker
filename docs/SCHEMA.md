# Achievement Schema Documentation

## File Structure

Each game has a JSON file with this structure:

```json
{
  "game": {
    "name": "Pokemon Game Name",
    "platform": "gb|gbc|gba|ds|etc",
    "generation": 1-9,
    "rom_hash": "SHA1 hash of ROM for identification"
  },
  "achievements": [
    {
      "id": "unique_identifier",
      "name": "Achievement Name",
      "description": "What the player needs to do",
      "category": "story|gym|elite_four|legendary|pokedex|collection|special",
      "icon": "icon_filename.png",
      "target_value": 1,
      "rarity": "common|uncommon|rare|epic|legendary",
      "memory_address": "0xADDRESS",
      "memory_condition": "condition_to_check",
      "points": 10
    }
  ]
}
```

## Fields

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (use snake_case) |
| `name` | string | Display name of achievement |
| `description` | string | What the player needs to do |
| `category` | string | Category (see below) |
| `target_value` | number | Value needed to unlock |
| `rarity` | string | common/uncommon/rare/epic/legendary |
| `points` | number | Points awarded |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `icon` | string | Icon filename |
| `memory_address` | string | Memory address to read |
| `memory_condition` | string | Condition to evaluate |

## Categories

- `story` - Main story progression
- `gym` - Gym badge achievements
- `elite_four` - Elite Four related
- `champion` - Becoming champion
- `legendary` - Legendary Pokemon
- `pokedex` - Pokedex completion
- `collection` - Item/ Pokemon collection
- `special` - Special/secret achievements
- `battle_frontier` - Battle Frontier (Gen 3+)
- `contest` - Pokemon contests (Gen 3+)

## Rarity Guidelines

| Rarity | Point Range | Description |
|--------|-------------|-------------|
| common | 10-30 | Easy, expected progress |
| uncommon | 30-75 | Takes some effort |
| rare | 100-200 | Significant challenge |
| epic | 200-500 | Major accomplishment |
| legendary | 1000+ | Extremely difficult |

## Memory Conditions

Use these operators for memory conditions:

- `== 5` - Equal to 5
- `!= 0` - Not equal to 0
- `> 10` - Greater than 10
- `< 100` - Less than 100
- `>= 50` - Greater than or equal to 50
- `<= 10` - Less than or equal to 10
- `& 0x01` - Bitwise AND (for flags)

## Example Achievement

```json
{
  "id": "red_champion_blue",
  "name": "Kanto Champion",
  "description": "Defeat your rival and become the Pokemon Champion",
  "category": "champion",
  "icon": "champion.png",
  "target_value": 1,
  "rarity": "epic",
  "memory_address": "0xD357",
  "memory_condition": "& 0x01",
  "points": 500
}
```

## Contributing New Games

1. Create a new JSON file: `achievements/games/pokemon_[game].json`
2. Include at least 30 achievements
3. Cover: Story, Gyms, Elite Four, Legendaries, Collection
4. Test memory addresses if possible
5. Submit PR with description

## Finding Memory Addresses

Resources for finding memory addresses:
- [Datacrystal](https://datacrystal.romhacking.net) - ROM hacking wiki
- [Pokemon disassemblies](https://github.com/pret) - Official disassemblies
- Cheat databases (for reference only)
