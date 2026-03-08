# PokeAchieve Platform API Guide
*Internal Documentation - For Zak's Reference Only*

---

## Overview

**Base URL:** `https://pokeachieve.com`  
**API Version:** 1.0.0  
**Framework:** FastAPI + SQLAlchemy + SQLite  
**Authentication:** JWT Tokens (web) + API Keys (tracker)

---

## Authentication Methods

### 1. JWT Token Auth (Web/Users)
For web dashboard and user-facing endpoints:
```
Authorization: Bearer <jwt_token>
```

**Obtain Token:**
```bash
POST /auth/login
{
  "username": "Zakypew",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### 2. API Key Auth (Tracker/Devices)
For tracker integration and automated clients:
```
Authorization: Bearer pk_<64_char_key>
```

**Generate Key:**
```bash
POST /user/api-key
Authorization: Bearer <jwt_token>
{
  "name": "Desktop Tracker"
}
```

**Response:**
```json
{
  "key": "pk_3fP2MF6bz7r3f43doJYOsLjJXmEi5g_oTGkkryxWNT8",
  "id": 1,
  "name": "Desktop Tracker",
  "created_at": "2026-03-04T12:00:00"
}
```

**⚠️ Key is shown ONLY once - store it securely!**

---

## Database Schema

### Users Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| username | String | Unique |
| email | String | Unique |
| hashed_password | String | bcrypt |
| created_at | DateTime | Auto |
| is_active | Boolean | Default true |
| twitch_url | String | Nullable |
| youtube_url | String | Nullable |
| tiktok_url | String | Nullable |

### Games Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| name | String | "Pokemon Red" |
| platform | String | "gba", "ds" |
| generation | Integer | 1-9 |
| rom_hash | String | For ROM detection |
| cover_image | String | URL/path |
| created_at | DateTime | Auto |

### Achievements Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK (internal) |
| string_id | String | "red_starter_chosen" (tracker ID) |
| game_id | Integer | FK → games |
| name | String | Display name |
| description | Text | Full description |
| category | String | "pokedex", "gym", "legendary" |
| icon | String | Icon URL/path |
| target_value | Integer | Usually 1 |
| rarity | String | common/uncommon/rare/epic/legendary |
| memory_address | String | RetroArch addr |
| memory_condition | String | "== 1", ">= 8" |
| points | Integer | Default 10 |

### UserAchievements Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users |
| achievement_id | Integer | FK → achievements |
| current_value | Integer | Progress |
| unlocked | Boolean | Completed? |
| unlocked_at | DateTime | When completed |
| updated_at | DateTime | Last update |

### PokemonCollection Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users |
| pokemon_id | Integer | 1-386 (Gen 1-3) |
| pokemon_name | String | "Pikachu" |
| caught | Boolean | Has it? |
| caught_at | DateTime | When caught |
| shiny | Boolean | Shiny variant? |
| shiny_caught_at | DateTime | When caught shiny |
| game | String | "Pokemon Red" |
| level | Integer | Level at catch |
| location | String | Where caught |
| nickname | String | User nickname |
| in_party | Boolean | Currently in party |
| party_slot | Integer | 1-6 |

### GameSessions Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users |
| game_id | Integer | FK → games |
| started_at | DateTime | Session start |
| ended_at | DateTime | Session end |
| active | Boolean | Currently playing? |
| play_time_seconds | Integer | Total time |

### APIKeys Table
| Field | Type | Notes |
|-------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users |
| key_hash | String | SHA256 of key |
| name | String | Friendly name |
| created_at | DateTime | Auto |
| last_used_at | DateTime | Updated on use |
| is_active | Boolean | Can be revoked |

---

## API Endpoints Reference

### 🔐 Authentication Endpoints

#### POST /auth/register
Create new user account.

**Request:**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Response:** `UserResponse`

#### POST /auth/login
Get JWT access token.

**Request:**
```json
{
  "username": "Zakypew",
  "password": "daddy2026!"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

---

### 👤 User Endpoints (JWT Required)

#### GET /users/me
Get current user profile.

**Headers:** `Authorization: Bearer <jwt>`

**Response:** `UserResponse`
```json
{
  "id": 6,
  "username": "Zakypew",
  "email": "zak.harris@gmail.com",
  "created_at": "2026-02-20T10:00:00",
  "is_active": true,
  "twitch_url": null,
  "youtube_url": null,
  "tiktok_url": null
}
```

#### GET /users/me/achievements
Get user's unlocked achievements.

**Query Params:**
- `game_id` (optional) - Filter by game

**Response:** `List[UserAchievementResponse]`

#### GET /users/me/stats
Get comprehensive stats.

**Response:**
```json
{
  "total_achievements_unlocked": 45,
  "total_achievements_available": 200,
  "overall_completion": 22.5,
  "game_stats": [
    {
      "game_id": 1,
      "game_name": "Pokemon Red",
      "total_achievements": 50,
      "unlocked_achievements": 25,
      "completion_percentage": 50.0
    }
  ]
}
```

---

### 🎮 Game Endpoints

#### GET /games
List all supported games.

**Response:** `List[GameResponse]`

#### GET /games/{game_id}
Get specific game details.

#### GET /games/{game_id}/achievements
Get all achievements for a game.

---

### 🏆 Achievement Endpoints

#### POST /achievements
Create new achievement (admin).

**Request:** `AchievementCreate`
```json
{
  "game_id": 1,
  "name": "First Steps",
  "description": "Choose your starter Pokemon",
  "category": "story",
  "rarity": "common",
  "points": 10,
  "memory_address": "0xD163",
  "memory_condition": "> 0"
}
```

#### POST /progress/update
Update achievement progress (web).

**Request:** `UserAchievementUpdate`
```json
{
  "achievement_id": 123,
  "current_value": 1,
  "unlocked": true
}
```

---

### 📱 Tracker Endpoints (API Key Required)

#### POST /api/tracker/test
Validate API key connectivity.

**Headers:** `Authorization: Bearer pk_...`

**Response:**
```json
{
  "message": "API key valid",
  "username": "Zakypew"
}
```

#### GET /api/tracker/progress/{game_id}
Get unlocked achievements for game (for sync).

**Response:**
```json
{
  "unlocked_achievement_ids": ["red_starter_chosen", "red_pokedex_10"]
}
```

#### POST /api/tracker/unlock
Unlock an achievement.

**Request:** `TrackerAchievementUnlock`
```json
{
  "game_id": 1,
  "achievement_id": "red_starter_chosen",
  "unlocked_at": "2026-03-04T14:30:00Z"
}
```

---

### 📊 Collection Endpoints

#### GET /api/collection
Get full collection summary.

**Response:** `PokemonCollectionResponse`
```json
{
  "total_caught": 45,
  "total_shiny": 2,
  "completion_percentage": 11.7,
  "collection": [...],
  "party": [...]
}
```

#### POST /api/collection/update
Update single Pokemon entry.

**Request:** `PokemonCollectionUpdate`
```json
{
  "pokemon_id": 25,
  "pokemon_name": "Pikachu",
  "caught": true,
  "caught_at": "2026-03-04T14:30:00Z",
  "shiny": false,
  "game": "Pokemon Red",
  "level": 5,
  "in_party": true,
  "party_slot": 1
}
```

#### POST /api/collection/batch-update
Bulk update collection.

**Request:** `List[PokemonCollectionUpdate]`

#### POST /api/collection/party
Update party slot assignment.

**Request:** `PartyUpdate`
```json
{
  "pokemon_id": 25,
  "in_party": true,
  "party_slot": 1
}
```

---

### 🔑 API Key Management

#### GET /user/api-keys
List all API keys.

**Response:** `List[APIKeyResponse]`

#### POST /user/api-key
Generate new API key.

**Request:** `APIKeyCreate`
```json
{
  "name": "Laptop Tracker"
}
```

**Response:** `APIKeyCreateResponse` (key shown once!)

#### DELETE /user/api-key/{key_id}
Revoke an API key.

---

### 🎮 Game Sessions

#### POST /sessions/start
Start a game session.

**Request:** `GameSessionCreate`
```json
{
  "game_id": 1
}
```

**Response:** `GameSessionResponse`

#### POST /sessions/{session_id}/end
End a game session.

---

### 📺 Overlay Endpoints

#### GET /overlay/{username}
Get public overlay data for streamers.

**Response:**
```json
{
  "username": "Zakypew",
  "current_game": "Pokemon Red",
  "progress": {...},
  "recent_achievements": [...]
}
```

---

### 🏥 Health Check

#### GET /health
Simple health check.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

## Tracker Integration Guide

### Game ID Mapping
```python
GAME_IDS = {
    "Pokemon Red": 1,
    "Pokemon Blue": 2,
    "Pokemon Emerald": 3,
    "Pokemon FireRed": 4,
    "Pokemon LeafGreen": 5,
    "Pokemon Gold": 6,
    "Pokemon Silver": 7,
    "Pokemon Crystal": 8,
    "Pokemon Ruby": 9,
    "Pokemon Sapphire": 10,
}
```

### Memory Address Reference (Gen 1)
```python
"pokemon_red": {
    "gen": 1,
    "max_pokemon": 151,
    "pokedex_seen": "0xD2F7",      # Encountered
    "pokedex_caught": "0xD30A",    # Actually caught
    "party_count": "0xD163",
    "party_start": "0xD16B",
    "party_slot_size": 44,
}
```

### Memory Address Reference (Gen 3)
```python
"pokemon_emerald": {
    "gen": 3,
    "max_pokemon": 386,
    "pokedex_seen": "0x02024C0C",
    "pokedex_caught": "0x02024D0C",
    "party_count": "0x02024284",
    "party_start": "0x02024284",
    "party_slot_size": 100,
}
```

---

## WebSocket Real-Time Updates

**URL:** `wss://pokeachieve.com/ws`

**Auth:** JWT token in connection headers

**Events:**
- `achievement_unlocked` - When user unlocks achievement

```json
{
  "type": "achievement_unlocked",
  "data": {
    "achievement_id": 123,
    "name": "First Steps",
    "description": "Choose your starter",
    "icon": "/icons/first_steps.png",
    "rarity": "common"
  }
}
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| 400 | Bad Request |
| 401 | Unauthorized (invalid token/key) |
| 404 | Not Found |
| 422 | Validation Error |
| 500 | Server Error |

---

## Python SDK Example

```python
import requests
from typing import Optional

class PokeAchieveAPI:
    def __init__(self, api_key: str, base_url: str = "https://pokeachieve.com"):
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def test_auth(self) -> tuple[bool, str]:
        """Test API key is valid"""
        resp = requests.get(
            f"{self.base_url}/api/users/me",
            headers=self.headers
        )
        if resp.status_code == 200:
            return True, resp.json().get("username")
        return False, resp.json().get("detail", "Auth failed")
    
    def unlock_achievement(self, game_id: int, achievement_id: str) -> bool:
        """Unlock an achievement"""
        resp = requests.post(
            f"{self.base_url}/api/tracker/unlock",
            headers=self.headers,
            json={
                "game_id": game_id,
                "achievement_id": achievement_id
            }
        )
        return resp.status_code == 200
    
    def update_collection(self, pokemon_id: int, caught: bool = True) -> bool:
        """Mark Pokemon as caught"""
        resp = requests.post(
            f"{self.base_url}/api/collection/update",
            headers=self.headers,
            json={
                "pokemon_id": pokemon_id,
                "pokemon_name": self._get_name(pokemon_id),
                "caught": caught
            }
        )
        return resp.status_code == 200
    
    def _get_name(self, pokemon_id: int) -> str:
        # Pokemon ID to name mapping
        names = {1: "Bulbasaur", 25: "Pikachu", ...}
        return names.get(pokemon_id, f"Pokemon #{pokemon_id}")

# Usage
api = PokeAchieveAPI("pk_3fP2MF6bz7r3f43doJYOsLjJXmEi5g_oTGkkryxWNT8")
success, username = api.test_auth()
print(f"Connected as: {username}")
```

---

## RetroArch Integration

**Network Command Interface:**
- Default Host: `127.0.0.1`
- Default Port: `55355`
- Protocol: UDP

**Enable in RetroArch:**
Settings → Network → Network Command Enable → ON

**Commands:**
```
READ_CORE_MEMORY <address> <bytes>
GET_STATUS
```

**Example Memory Read:**
```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b"READ_CORE_MEMORY 0xD30A 19\n", ("127.0.0.1", 55355))
response, _ = sock.recvfrom(4096)
# Parse: "READ_CORE_MEMORY 0xD30A ff ff ff..."
```

---

## Deployment Info

**Server:** PokeAchieve VPS (DigitalOcean)  
**IP:** 66.175.239.154  
**Path:** `/home/pokeachieve/backend/`  
**Service:** `pokeachieve.service` (systemd)  
**Database:** SQLite (`./pokeachieve.db`)

**Start/Stop:**
```bash
systemctl start pokeachieve
systemctl stop pokeachieve
systemctl restart pokeachieve
```

**Logs:**
```bash
journalctl -u pokeachieve -f
```

---

## Environment Variables

```bash
# Database
DATABASE_URL=sqlite:///./pokeachieve.db

# JWT Secret (for token signing)
SECRET_KEY=your-secret-key-here

# Email (for password reset)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASS=your-app-password
```

---

## Related Repositories

| Repo | Purpose |
|------|---------|
| `pokeachieve-platform` | Main website backend/frontend |
| `pokeachieve-tracker` | Desktop tracker application |

---

*Generated: 2026-03-04*  
*For internal use only - Do not distribute* 🔒
