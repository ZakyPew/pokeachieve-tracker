# Tracker Integration Guide

**Project:** PokeAchieve Tracker  
**Purpose:** Connect RetroArch to PokeAchieve platform for real-time achievement and collection tracking

---

## API Authentication

All tracker requests must include API key authentication:

```http
Authorization: Bearer YOUR_API_KEY
```

Get your API key from: Dashboard → API Keys → Generate New Key

---

## Achievement Tracking

### POST `/api/tracker/unlock`

Report achievement unlock to platform.

**Request:**
```json
{
  "game_id": 1,
  "achievement_id": "pokemon_red_the_journey_begins",
  "unlocked_at": "2026-02-23T22:30:00Z"
}
```

**Response:**
```json
{
  "success": true,
  "new_unlock": true,
  "achievement_name": "The Journey Begins",
  "points": 10
}
```

### GET `/api/tracker/progress/{game_id}`

Get user's progress for game (sync on startup).

**Response:**
```json
{
  "game_id": 1,
  "total_achievements": 48,
  "unlocked_count": 12,
  "unlocked_achievement_ids": [
    "pokemon_red_the_journey_begins",
    "pokemon_red_bug_catcher"
  ]
}
```

---

## Pokemon Collection Tracking

### POST `/api/collection/update`

Update single Pokemon entry.

**Request:**
```json
{
  "pokemon_id": 25,
  "pokemon_name": "pikachu",
  "caught": true,
  "caught_at": "2026-02-23T22:30:00Z",
  "shiny": false,
  "game": "Pokemon Yellow",
  "level": 25,
  "location": "Viridian Forest"
}
```

### POST `/api/collection/batch-update`

Sync multiple Pokemon at once (recommended for tracker).

**Request:**
```json
[
  {
    "pokemon_id": 1,
    "pokemon_name": "bulbasaur",
    "caught": true,
    "shiny": false,
    "game": "Pokemon Red"
  },
  {
    "pokemon_id": 4,
    "pokemon_name": "charmander",
    "caught": true,
    "shiny": true,
    "game": "Pokemon Red"
  }
]
```

### POST `/api/collection/party`

Update current party status.

**Request:**
```json
{
  "pokemon_id": 6,
  "in_party": true,
  "party_slot": 1
}
```

### GET `/api/collection`

Get user's full collection.

**Query Params:**
- `generation` (optional): Filter by gen (1, 2, 3)
- `caught_only` (optional): Only show caught

**Response:**
```json
{
  "total_caught": 42,
  "total_shiny": 3,
  "completion_percentage": 4.15,
  "collection": [...],
  "party": [...]
}
```

---

## Memory Addresses for RetroArch

### Pokemon Red/Blue (Gen 1)

**Pokedex Flags:**
- Address: `0xD2F7` - `0xD31C` (386 bits = 151 Pokemon)
- Each bit represents caught status
- Bit 0 = Pokemon #1 (Bulbasaur), Bit 1 = Pokemon #2, etc.

**Current Party:**
- Party count: `0xD163`
- Pokemon 1: `0xD16B` - `0xD197` (44 bytes each)
- Pokemon 2: `0xD198` - `0xD1C4`
- etc.

**Pokemon Structure (44 bytes):**
- Byte 0: Species ID
- Byte 1: Current HP (low)
- Byte 2: Current HP (high)
- Byte 3: Level
- Byte 4: Status condition
- Bytes 5-12: Types, catch rate, moves
- Bytes 13-23: OT ID, experience
- Bytes 24-43: IVs, EVs

### Pokemon Gold/Silver (Gen 2)

**Pokedex Flags:**
- Address: `0xDDA4` - `0xDDDF` (251 Pokemon)

**Current Party:**
- Party count: `0xDA22`
- Pokemon 1: `0xDA2A` - `0xDA56`

### Pokemon Emerald (Gen 3)

**Pokedex Flags:**
- Address: `0x202F900` - `0x202F9C` (386 Pokemon)

**Current Party:**
- Party count: `0x20244E0`
- Pokemon 1: `0x20244E8`

---

## Reading Pokemon Data

### Step 1: Check if Pokemon is Caught

```python
def is_pokemon_caught(memory, pokemon_id):
    """Check if Pokemon is caught using Pokedex flags"""
    byte_index = (pokemon_id - 1) // 8
    bit_index = (pokemon_id - 1) % 8
    byte_value = memory[0xD2F7 + byte_index]
    return (byte_value >> bit_index) & 1
```

### Step 2: Read Current Party

```python
def read_party(memory):
    """Read current party Pokemon"""
    party_count = memory[0xD163]
    party = []
    
    for i in range(party_count):
        offset = 0xD16B + (i * 44)
        species_id = memory[offset]
        level = memory[offset + 3]
        
        party.append({
            'species_id': species_id,
            'level': level,
            'slot': i + 1
        })
    
    return party
```

### Step 3: Sync to Platform

```python
import requests

def sync_collection(api_key, caught_pokemon, party):
    """Sync collection to PokeAchieve"""
    
    headers = {'Authorization': f'Bearer {api_key}'}
    
    # Build batch update
    batch = []
    for pokemon in caught_pokemon:
        batch.append({
            'pokemon_id': pokemon['id'],
            'pokemon_name': pokemon['name'],
            'caught': True,
            'shiny': pokemon.get('shiny', False),
            'game': 'Pokemon Red'
        })
    
    # Send to API
    response = requests.post(
        'http://66.175.239.154:8000/api/collection/batch-update',
        headers=headers,
        json=batch
    )
    
    # Update party
    for member in party:
        requests.post(
            'http://66.175.239.154:8000/api/collection/party',
            headers=headers,
            json={
                'pokemon_id': member['species_id'],
                'in_party': True,
                'party_slot': member['slot']
            }
        )
    
    return response.json()
```

---

## RetroArch Network Commands

Connect to RetroArch on port 55355:

```python
import socket

class RetroArchClient:
    def __init__(self, host='127.0.0.1', port=55355):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((host, port))
    
    def read_memory(self, address, length=1):
        """Read memory from RetroArch"""
        command = f'READ_CORE_MEMORY {address} {length}\n'
        self.socket.send(command.encode())
        response = self.socket.recv(4096).decode()
        # Parse response: "READ_CORE_MEMORY address length values..."
        parts = response.split()
        if len(parts) >= 3:
            values = [int(x, 16) for x in parts[2:]]
            return values[0] if length == 1 else values
        return None
    
    def get_current_game(self):
        """Get loaded ROM name"""
        self.socket.send(b'GET_CURRENT_GAME\n')
        return self.socket.recv(256).decode().strip()
```

---

## PokeAPI Sprite URLs

**Regular Sprites:**
```
https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png
```

**Shiny Sprites:**
```
https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{id}.png
```

**Official Artwork:**
```
https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{id}.png
```

---

## Testing the Tracker

1. **Generate API Key** in PokeAchieve Dashboard
2. **Start RetroArch** with Network Commands enabled (port 55355)
3. **Load Pokemon ROM**
4. **Run tracker** with your API key
5. **Catch a Pokemon** in game
6. **Check Collection page** - should show new catch!

---

## Troubleshooting

**"Invalid API key"**
- Verify key is active (not revoked)
- Check Authorization header format: `Bearer your_key_here`

**"Pokemon not found in collection"**
- Pokemon must be caught before adding to party
- Use `/api/collection/update` first, then `/api/collection/party`

**"Memory read failed"**
- Ensure RetroArch Network Commands is enabled
- Check port 55355 is not blocked
- Verify game is loaded (not in menu)

**Rate Limiting**
- Batch updates recommended: `/api/collection/batch-update`
- Max 100 Pokemon per batch request

---

## File Locations

**Tracker Code:**
- `~/projects/active/pokeachieve/tracker/gui/tracker_gui.py`

**Backend API:**
- `~/projects/active/pokeachieve/platform/backend/main.py`

**Collection Model:**
- `~/projects/active/pokeachieve/platform/backend/models.py` (PokemonCollection)

**Live API:**
- `http://66.175.239.154:8000`

---

*Last Updated: 2026-02-23*
