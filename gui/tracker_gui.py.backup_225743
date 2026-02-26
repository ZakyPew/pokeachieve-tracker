"""
PokeAchieve Tracker - Cross-Platform GUI with API Integration
Connects to RetroArch and syncs achievements + Pokemon collection to PokeAchieve platform
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import socket
import json
import time
import threading
import queue
import re
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class Achievement:
    id: str
    name: str
    description: str
    category: str
    rarity: str
    points: int
    memory_address: str
    memory_condition: str
    unlocked: bool = False
    unlocked_at: Optional[str] = None


@dataclass
class Pokemon:
    id: int
    name: str
    level: Optional[int] = None
    shiny: bool = False
    in_party: bool = False
    party_slot: Optional[int] = None


class PokeAchieveAPI:
    """Client for PokeAchieve platform API"""
    
    def __init__(self, base_url: str = "https://pokeachieve.com/api", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    
    def _request(self, method: str, endpoint: str, data: dict = None) -> tuple[bool, dict]:
        """Make API request and return (success, response_data)"""
        url = f"{self.base_url}{endpoint}"
        print(f"[API REQUEST] {method} {url}")
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode() if data else None,
                headers=self.headers,
                method=method
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.getcode()
                body = response.read().decode()
                print(f"[API SUCCESS] {method} {endpoint} -> HTTP {status}")
                return True, json.loads(body)
        except urllib.error.HTTPError as e:
            status = e.getcode()
            error_body = e.read().decode()
            print(f"[API ERROR] {method} {endpoint} -> HTTP {status}: {error_body[:200]}")
            try:
                error_data = json.loads(error_body)
                return False, {"error": error_data.get("detail", str(e)), "status": status}
            except:
                return False, {"error": f"HTTP {status}: {error_body[:200]}", "status": status}
        except Exception as e:
            print(f"[API ERROR] {method} {endpoint} -> {type(e).__name__}: {str(e)}")
            return False, {"error": str(e)}
    
    def test_auth(self) -> tuple[bool, str]:
        """Test API key authentication"""
        success, data = self._request("POST", "/tracker/test")
        if success:
            return True, data.get("message", "Authentication successful")
        return False, data.get("error", "Authentication failed")
    
    def get_progress(self, game_id: int) -> tuple[bool, list]:
        """Get user's progress for a game"""
        success, data = self._request("GET", f"/tracker/progress/{game_id}")
        if success:
            return True, data.get("unlocked_achievement_ids", [])
        return False, []
    
    def post_unlock(self, game_id: int, achievement_id: str) -> tuple[bool, dict]:
        """Post achievement unlock to platform"""
        payload = {
            "game_id": game_id,
            "achievement_id": achievement_id,
            "unlocked_at": datetime.now().isoformat()
        }
        return self._request("POST", "/tracker/unlock", payload)
    
    # Pokemon Collection API Methods
    def post_collection_batch(self, pokemon_list: List[Dict]) -> tuple[bool, dict]:
        """Post batch of Pokemon collection updates"""
        return self._request("POST", "/collection/batch-update", pokemon_list)
    
    def post_party_update(self, pokemon_id: int, in_party: bool, party_slot: int = None) -> tuple[bool, dict]:
        """Update party status for a Pokemon"""
        payload = {
            "pokemon_id": pokemon_id,
            "in_party": in_party,
            "party_slot": party_slot
        }
        return self._request("POST", "/collection/party", payload)


class RetroArchClient:
    """Client for connecting to RetroArch network command interface"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 55355):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect to RetroArch"""
        try:
            with self.lock:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.settimeout(5)
                # UDP does not need connect
                self.connected = True
            return True
        except Exception as e:
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from RetroArch"""
        with self.lock:
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
    
    def send_command(self, command: str) -> Optional[str]:
        """Send a command to RetroArch and get response"""
        with self.lock:
            if not self.connected or not self.socket:
                return None
            
            try:
                # UDP uses sendto and recvfrom
                self.socket.sendto(f"{command}\n".encode(), (self.host, self.port))
                response, addr = self.socket.recvfrom(4096)
                return response.decode().strip()
            except Exception as e:
                self.connected = False
                return None
    
    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        if response and response.startswith("GET_STATUS"):
            # Parse: GET_STATUS PAUSED game_boy,Pokemon Red(Enhanced),crc32=...
            try:
                parts = response.replace("GET_STATUS ", "").split(",")
                if len(parts) >= 2:
                    return parts[1].strip()  # Pokemon name is 2nd part
            except:
                pass
        return None
    
    def read_memory(self, address: str, num_bytes: int = 1) -> Optional[int]:
        """Read memory from the emulator"""
        response = self.send_command(f"READ_CORE_MEMORY {address} {num_bytes}")
        if response and response.startswith("READ_CORE_MEMORY"):
            parts = response.split()
            if len(parts) >= 3:
                try:
                    values = [int(x, 16) for x in parts[2:]]
                    return values[0] if len(values) == 1 else values
                except ValueError:
                    pass
        return None
    
    def get_status(self) -> Dict:
        """Get RetroArch status"""
        response = self.send_command("GET_STATUS")
        if response:
            parts = response.split(",")
            return {
                "status": parts[0] if parts else "UNKNOWN",
                "game": parts[1] if len(parts) > 1 else None,
                "raw": response
            }
        return {"status": "DISCONNECTED", "game": None}


class PokemonMemoryReader:
    """Reads Pokemon data from game memory"""
    
    # Memory addresses for different games
    GAME_ADDRESSES = {
        # Gen 1 (151 Pokemon)
        "pokemon_red": {
            "gen": 1,
            "max_pokemon": 151,
            "pokedex_seen": "0xD2F7",      # Pokemon you've encountered
            "pokedex_caught": "0xD30A",    # Pokemon you've actually CAUGHT ⭐
            "party_count": "0xD163",
            "party_start": "0xD16B",
            "party_slot_size": 44,
        },
        "pokemon_blue": {
            "gen": 1,
            "max_pokemon": 151,
            "pokedex_seen": "0xD2F7",
            "pokedex_caught": "0xD30A",
            "party_count": "0xD163",
            "party_start": "0xD16B",
            "party_slot_size": 44,
        },
        "pokemon_yellow": {
            "gen": 1,
            "max_pokemon": 151,
            "pokedex_seen": "0xD2F7",
            "pokedex_caught": "0xD30A",
            "party_count": "0xD163",
            "party_start": "0xD16B",
            "party_slot_size": 44,
        },
        # Gen 2 (251 Pokemon)
        "pokemon_gold": {
            "gen": 2,
            "max_pokemon": 251,
            "pokedex_seen": "0xDDA4",
            "pokedex_caught": "0xDC44",    # Gen 2 caught flags
            "party_count": "0xDA22",
            "party_start": "0xDA2A",
            "party_slot_size": 48,
        },
        "pokemon_silver": {
            "gen": 2,
            "max_pokemon": 251,
            "pokedex_seen": "0xDDA4",
            "pokedex_caught": "0xDC44",
            "party_count": "0xDA22",
            "party_start": "0xDA2A",
            "party_slot_size": 48,
        },
        "pokemon_crystal": {
            "gen": 2,
            "max_pokemon": 251,
            "pokedex_seen": "0xDDA4",
            "pokedex_caught": "0xDC44",
            "party_count": "0xDA22",
            "party_start": "0xDA2A",
            "party_slot_size": 48,
        },
        # Gen 3 (386 Pokemon)
        "pokemon_ruby": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_flags": "0x202F900",
            "party_count": "0x20244E0",
            "party_start": "0x20244E8",
            "party_slot_size": 100,
        },
        "pokemon_sapphire": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_flags": "0x202F900",
            "party_count": "0x20244E0",
            "party_start": "0x20244E8",
            "party_slot_size": 100,
        },
        "pokemon_emerald": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x202F900",
            "pokedex_caught": "0x202F900",  # TODO: Find correct caught address for Gen 3
            "party_count": "0x20244E0",
            "party_start": "0x20244E8",
            "party_slot_size": 100,
        },
        "pokemon_firered": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x202F900",
            "pokedex_caught": "0x202F900",  # TODO: Find correct caught address for Gen 3
            "party_count": "0x20244E0",
            "party_start": "0x20244E8",
            "party_slot_size": 100,
        },
        "pokemon_leafgreen": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x202F900",
            "pokedex_caught": "0x202F900",  # TODO: Find correct caught address for Gen 3
            "party_count": "0x20244E0",
            "party_start": "0x20244E8",
            "party_slot_size": 100,
        },
    }
    
    # Pokemon names lookup (Gen 1-3)
    POKEMON_NAMES = {
        1: "Bulbasaur", 2: "Ivysaur", 3: "Venusaur",
        4: "Charmander", 5: "Charmeleon", 6: "Charizard",
        7: "Squirtle", 8: "Wartortle", 9: "Blastoise",
        25: "Pikachu", 26: "Raichu",
        29: "Nidoran♀", 32: "Nidoran♂",
        43: "Oddish", 44: "Gloom", 45: "Vileplume",
        50: "Diglett", 51: "Dugtrio",
        52: "Meowth", 53: "Persian",
        54: "Psyduck", 55: "Golduck",
        58: "Growlithe", 59: "Arcanine",
        60: "Poliwag", 61: "Poliwhirl", 62: "Poliwrath",
        63: "Abra", 64: "Kadabra", 65: "Alakazam",
        66: "Machop", 67: "Machoke", 68: "Machamp",
        69: "Bellsprout", 70: "Weepinbell", 71: "Victreebel",
        74: "Geodude", 75: "Graveler", 76: "Golem",
        77: "Ponyta", 78: "Rapidash",
        79: "Slowpoke", 80: "Slowbro",
        81: "Magnemite", 82: "Magneton",
        83: "Farfetch'd",
        88: "Grimer", 89: "Muk",
        92: "Gastly", 93: "Haunter", 94: "Gengar",
        95: "Onix",
        104: "Cubone", 105: "Marowak",
        111: "Rhyhorn", 112: "Rhydon",
        113: "Chansey",
        115: "Kangaskhan",
        122: "Mr. Mime",
        123: "Scyther",
        124: "Jynx",
        125: "Electabuzz",
        126: "Magmar",
        127: "Pinsir",
        128: "Tauros",
        129: "Magikarp", 130: "Gyarados",
        131: "Lapras",
        132: "Ditto",
        133: "Eevee", 134: "Vaporeon", 135: "Jolteon", 136: "Flareon",
        143: "Snorlax",
        147: "Dratini", 148: "Dragonair", 149: "Dragonite",
        150: "Mewtwo", 151: "Mew",
        # Gen 2 starters
        152: "Chikorita", 153: "Bayleef", 154: "Meganium",
        155: "Cyndaquil", 156: "Quilava", 157: "Typhlosion",
        158: "Totodile", 159: "Croconaw", 160: "Feraligatr",
        # Legendaries
        243: "Raikou", 244: "Entei", 245: "Suicune",
        249: "Lugia", 250: "Ho-Oh", 251: "Celebi",
        # Gen 3 starters
        252: "Treecko", 253: "Grovyle", 254: "Sceptile",
        255: "Torchic", 256: "Combusken", 257: "Blaziken",
        258: "Mudkip", 259: "Marshtomp", 260: "Swampert",
        # Gen 3 legendaries
        377: "Regirock", 378: "Regice", 379: "Registeel",
        380: "Latias", 381: "Latios",
        382: "Kyogre", 383: "Groudon", 384: "Rayquaza",
        385: "Jirachi", 386: "Deoxys",
    }
    
    def __init__(self, retroarch: RetroArchClient):
        self.retroarch = retroarch
    
    def get_pokemon_name(self, pokemon_id: int) -> str:
        """Get Pokemon name from ID"""
        return self.POKEMON_NAMES.get(pokemon_id, f"Pokemon #{pokemon_id}")
    
    def get_game_config(self, game_name: str) -> Optional[Dict]:
        """Get memory addresses for current game"""
        # Strip ROM hack suffixes like "(Enhanced)", "(U)", etc.
        clean_name = re.sub(r'\([^)]*\)', '', game_name)
        game_key = clean_name.lower().replace(" ", "_").strip()
        return self.GAME_ADDRESSES.get(game_key)
    
    def read_pokedex(self, game_name: str) -> List[int]:
        """Read Pokedex CAUGHT flags - returns list of CAUGHT Pokemon IDs (not seen!)"""
        config = self.get_game_config(game_name)
        if not config:
            return []
        
        caught = []
        # Use pokedex_caught address (0xD30A for Gen 1) not pokedex_seen (0xD2F7)!
        # pokedex_seen = every Pokemon you encountered
        # pokedex_caught = only Pokemon you actually caught
        pokedex_addr = config.get("pokedex_caught", config.get("pokedex_flags", "0xD2F7"))
        
        # Read bytes - each byte contains 8 Pokemon flags
        # Gen 1: 151 Pokemon = 19 bytes
        # Gen 2: 251 Pokemon = 32 bytes  
        # Gen 3: 386 Pokemon = 49 bytes
        
        max_pokemon = 151 if config["gen"] == 1 else (251 if config["gen"] == 2 else 386)
        num_bytes = (max_pokemon + 7) // 8
        
        for byte_idx in range(num_bytes):
            addr = hex(int(pokedex_addr, 16) + byte_idx)
            byte_val = self.retroarch.read_memory(addr)
            
            if byte_val is None:
                continue
            
            # Check each bit in the byte
            for bit_idx in range(8):
                pokemon_id = byte_idx * 8 + bit_idx + 1
                if pokemon_id > max_pokemon:
                    break
                
                if (byte_val >> bit_idx) & 1:
                    caught.append(pokemon_id)
        
        return caught
    
    def read_party(self, game_name: str) -> List[Dict]:
        """Read current party Pokemon"""
        config = self.get_game_config(game_name)
        if not config:
            return []
        
        party = []
        party_count_addr = config["party_count"]
        party_start_addr = config["party_start"]
        slot_size = config["party_slot_size"]
        
        # Read party count
        count = self.retroarch.read_memory(party_count_addr)
        if count is None or count > 6:
            return []
        
        # Read each party member
        for i in range(count):
            slot_addr = hex(int(party_start_addr, 16) + (i * slot_size))
            
            # Read species ID (first byte of structure)
            species_id = self.retroarch.read_memory(slot_addr)
            if species_id is None or species_id == 0:
                continue
            
            # Read level (offset depends on generation)
            level_offset = 3 if config["gen"] in [1, 2] else 4
            level_addr = hex(int(slot_addr, 16) + level_offset)
            level = self.retroarch.read_memory(level_addr)
            
            party.append({
                "id": species_id,
                "level": level if level else None,
                "slot": i + 1
            })
        
        return party


class AchievementTracker:
    """Tracks achievements and reports unlocks"""
    
    # Game ID mapping (must match platform database)
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
    
    def __init__(self, retroarch: RetroArchClient, api: Optional[PokeAchieveAPI] = None):
        self.retroarch = retroarch
        self.api = api
        self.pokemon_reader = PokemonMemoryReader(retroarch)
        self.achievements: List[Achievement] = []
        self.game_name: Optional[str] = None
        self.game_id: Optional[int] = None
        self.on_unlock: Optional[Callable] = None
        self.on_progress: Optional[Callable] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._unlock_queue: queue.Queue = queue.Queue()
        self._api_queue: queue.Queue = queue.Queue()
        self._collection_queue: queue.Queue = queue.Queue()
        self._last_party: List[Dict] = []
        self._last_pokedex: List[int] = []
    
    def load_game(self, game_name: str, achievements_file: Path) -> bool:
        """Load achievements for a specific game"""
        try:
            with open(achievements_file, 'r') as f:
                data = json.load(f)
            
            self.achievements = []
            for ach_data in data.get("achievements", []):
                self.achievements.append(Achievement(
                    id=ach_data["id"],
                    name=ach_data["name"],
                    description=ach_data["description"],
                    category=ach_data.get("category", "misc"),
                    rarity=ach_data.get("rarity", "common"),
                    points=ach_data.get("points", 10),
                    memory_address=ach_data.get("memory_address", ""),
                    memory_condition=ach_data.get("memory_condition", ""),
                ))
            
            self.game_name = game_name
            self.game_id = self.GAME_IDS.get(game_name)
            return True
        except Exception as e:
            return False
    
    def load_progress(self, progress_file: Path):
        """Load previously unlocked achievements"""
        if not progress_file.exists():
            return
        
        try:
            with open(progress_file, 'r') as f:
                data = json.load(f)
            
            unlocked_ids = set(data.get("unlocked", []))
            for ach in self.achievements:
                if ach.id in unlocked_ids:
                    ach.unlocked = True
        except:
            pass
    
    def save_progress(self, progress_file: Path):
        """Save unlocked achievements"""
        try:
            data = {
                "game": self.game_name,
                "unlocked": [ach.id for ach in self.achievements if ach.unlocked],
                "saved_at": datetime.now().isoformat()
            }
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            with open(progress_file, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass
    
    def sync_with_platform(self) -> tuple[int, int]:
        """Sync progress with platform. Returns (newly_synced, errors)"""
        if not self.api or not self.game_id:
            return 0, 0
        
        success, unlocked_ids = self.api.get_progress(self.game_id)
        if not success:
            return 0, 1
        
        newly_synced = 0
        for ach in self.achievements:
            if ach.id in unlocked_ids and not ach.unlocked:
                ach.unlocked = True
                newly_synced += 1
        
        return newly_synced, 0
    
    def check_achievements(self) -> List[Achievement]:
        """Check all achievements, return newly unlocked ones"""
        newly_unlocked = []
        
        for achievement in self.achievements:
            if achievement.unlocked:
                continue
            
            unlocked = False
            
            # Direct memory check (achievements with memory_address)
            if achievement.memory_address and achievement.memory_condition:
                value = self.retroarch.read_memory(achievement.memory_address)
                if value is not None:
                    if self.evaluate_condition(value, achievement.memory_condition):
                        unlocked = True
            
            # Derived achievement checks (achievements without direct memory addresses)
            else:
                unlocked = self._check_derived_achievement(achievement)
            
            if unlocked:
                achievement.unlocked = True
                achievement.unlocked_at = datetime.now().isoformat()
                newly_unlocked.append(achievement)
                self._unlock_queue.put(achievement)
                self.post_unlock_to_platform(achievement)
        
        return newly_unlocked
    
    def _check_derived_achievement(self, achievement: Achievement) -> bool:
        """Check achievements that require calculation from multiple memory locations"""
        if not self.game_name:
            return False
        
        game_key = self.game_name.lower().replace(" ", "_")
        ach_id = achievement.id
        
        # Pokedex achievements
        if "pokedex" in ach_id:
            return self._check_pokedex_achievement(achievement)
        
        # All gyms achievement
        if ach_id.endswith("_gym_all"):
            return self._check_all_gyms()
        
        # Elite Four achievements
        if "elite_four" in ach_id and not ach_id.endswith("_all"):
            return self._check_elite_four_member(achievement)
        
        # All Elite Four
        if ach_id.endswith("_elite_four_all"):
            return self._check_all_elite_four()
        
        # Legendary achievements (individual birds)
        if "legendary" in ach_id and any(x in ach_id for x in ["moltres", "zapdos", "articuno", "mewtwo"]):
            return self._check_legendary_caught(achievement)
        
        # All legendary birds
        if ach_id.endswith("_legendary_birds"):
            return self._check_all_legendary_birds()
        
        # All legendaries
        if ach_id.endswith("_legendary_all"):
            return self._check_all_legendaries()
        
        # First Steps - check if game has been started (has starter)
        if "first_steps" in ach_id:
            return self._check_first_steps()
        
        # Pokemon Master - all badges + champion + complete pokedex
        if "pokemon_master" in ach_id:
            return self._check_pokemon_master()
        
        return False
    
    def _check_pokedex_achievement(self, achievement: Achievement) -> bool:
        """Check pokedex count achievements"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        caught_count = len(current_pokedex)
        
        # Get target from achievement ID or description
        ach_id = achievement.id
        if "_pokedex_10" in ach_id or "_pokedex_beginner" in ach_id:
            return caught_count >= 10
        elif "_pokedex_25" in ach_id or "_pokedex_collector" in ach_id:
            return caught_count >= 25
        elif "_pokedex_50" in ach_id:
            return caught_count >= 50
        elif "_pokedex_100" in ach_id:
            return caught_count >= 100
        elif "_pokedex_150" in ach_id or "_pokedex_complete" in ach_id:
            return caught_count >= 150
        elif "_pokedex_151" in ach_id or "_pokedex_completionist" in ach_id:
            return caught_count >= 151
        
        return False
    
    def _check_all_gyms(self) -> bool:
        """Check if all 8 gym badges are obtained"""
        # Badge flags are at 0xD356 (Gen 1) or 0xD35C (Gen 2)
        badge_addr = "0xD356"  # Gen 1 default
        if "gold" in self.game_name.lower() or "silver" in self.game_name.lower() or "crystal" in self.game_name.lower():
            badge_addr = "0xD35C"
        
        badge_byte = self.retroarch.read_memory(badge_addr)
        if badge_byte is not None:
            # All 8 badges = all 8 bits set = 0xFF = 255
            return badge_byte == 0xFF
        return False
    
    def _check_elite_four_member(self, achievement: Achievement) -> bool:
        """Check if specific Elite Four member is defeated"""
        # Elite Four flags are in RAM, need to find correct addresses
        # Gen 1: Victory Road flags around 0xD6xx
        ach_id = achievement.id.lower()
        
        # Map achievement IDs to their defeat flags (these are approximate)
        e4_addresses = {
            "lorelei": "0xD6E0",
            "bruno": "0xD6E1", 
            "agatha": "0xD6E2",
            "lance": "0xD6E3"
        }
        
        for name, addr in e4_addresses.items():
            if name in ach_id:
                value = self.retroarch.read_memory(addr)
                if value is not None and value > 0:
                    return True
        
        return False
    
    def _check_all_elite_four(self) -> bool:
        """Check if all Elite Four members are defeated"""
        # Check all 4 E4 members
        e4_addresses = ["0xD6E0", "0xD6E1", "0xD6E2", "0xD6E3"]
        defeated_count = 0
        
        for addr in e4_addresses:
            value = self.retroarch.read_memory(addr)
            if value is not None and value > 0:
                defeated_count += 1
        
        return defeated_count >= 4
    
    def _check_legendary_caught(self, achievement: Achievement) -> bool:
        """Check if specific legendary is caught (via Pokedex)"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        ach_id = achievement.id.lower()
        
        legendary_ids = {
            "mewtwo": 150,
            "moltres": 146,
            "zapdos": 145,
            "articuno": 144
        }
        
        for name, pokemon_id in legendary_ids.items():
            if name in ach_id:
                return pokemon_id in current_pokedex
        
        return False
    
    def _check_all_legendary_birds(self) -> bool:
        """Check if all 3 legendary birds are caught"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        birds = [144, 145, 146]  # Articuno, Zapdos, Moltres
        
        return all(bird in current_pokedex for bird in birds)
    
    def _check_all_legendaries(self) -> bool:
        """Check if all legendaries are caught (birds + Mewtwo)"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        legendaries = [144, 145, 146, 150]  # Articuno, Zapdos, Moltres, Mewtwo
        
        return all(leg in current_pokedex for leg in legendaries)
    
    def _check_first_steps(self) -> bool:
        """Check if player has started the game (has a starter Pokemon in party)"""
        if not self.pokemon_reader:
            return False
        
        party = self.pokemon_reader.read_party(self.game_name)
        # Starters are Bulbasaur (1), Charmander (4), Squirtle (7)
        starter_ids = {1, 4, 7}
        
        for member in party:
            if member.get("id") in starter_ids:
                return True
        
        return False
    
    def _check_pokemon_master(self) -> bool:
        """Check Pokemon Master: All badges, Champion, and Complete Pokedex"""
        if not self.pokemon_reader:
            return False
        
        # Check all gyms
        if not self._check_all_gyms():
            return False
        
        # Check champion
        champion_addr = "0xD357"  # Champion flag
        value = self.retroarch.read_memory(champion_addr)
        if not (value and value & 0x01):
            return False
        
        # Check complete pokedex (151)
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        if len(current_pokedex) < 151:
            return False
        
        return True
    
    def check_collection(self):
        """Check Pokemon collection and queue updates"""
        if not self.game_name or not self.pokemon_reader:
            return
        
        # Read current Pokedex
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        
        # Read current party
        current_party = self.pokemon_reader.read_party(self.game_name)
        
        # Find new catches
        new_catches = [p for p in current_pokedex if p not in self._last_pokedex]
        
        # Find party changes
        party_changes = []
        for member in current_party:
            old_member = next((p for p in self._last_party if p["id"] == member["id"]), None)
            if not old_member:
                party_changes.append(member)
        
        # Queue updates if there are changes
        if new_catches or party_changes:
            self._collection_queue.put({
                "catches": new_catches,
                "party": current_party,
                "game": self.game_name
            })
        
        # Update last known state
        self._last_pokedex = current_pokedex
        self._last_party = current_party
    
    def post_unlock_to_platform(self, achievement: Achievement):
        """Queue achievement unlock for API posting"""
        if self.api and self.game_id:
            self._api_queue.put({"type": "achievement", "achievement": achievement})
    
    def post_collection_to_platform(self, catches: List[int], party: List[Dict], game: str):
        """Queue collection update for API posting"""
        if self.api:
            self._api_queue.put({
                "type": "collection",
                "catches": catches,
                "party": party,
                "game": game
            })
    
    def evaluate_condition(self, value: int, condition: str) -> bool:
        """Evaluate a memory condition"""
        condition = condition.strip()
        
        if condition.startswith(">="):
            try:
                return value >= int(condition[2:].strip())
            except:
                pass
        elif condition.startswith("<="):
            try:
                return value <= int(condition[2:].strip())
            except:
                pass
        elif condition.startswith(">"):
            try:
                return value > int(condition[1:].strip())
            except:
                pass
        elif condition.startswith("<"):
            try:
                return value < int(condition[1:].strip())
            except:
                pass
        elif condition.startswith("=="):
            try:
                return value == int(condition[2:].strip())
            except:
                pass
        elif condition.startswith("!="):
            try:
                return value != int(condition[2:].strip())
            except:
                pass
        elif condition.startswith("&"):
            try:
                target = int(condition[1:].strip(), 16) if "x" in condition else int(condition[1:].strip())
                return (value & target) == target
            except:
                pass
        
        return False
    
    def get_progress(self) -> Dict:
        """Get current progress stats"""
        total = len(self.achievements)
        unlocked = sum(1 for a in self.achievements if a.unlocked)
        points = sum(a.points for a in self.achievements if a.unlocked)
        total_points = sum(a.points for a in self.achievements)
        
        return {
            "total": total,
            "unlocked": unlocked,
            "percentage": (unlocked / total * 100) if total > 0 else 0,
            "points": points,
            "total_points": total_points
        }
    
    def start_polling(self, interval_ms: int = 500):
        """Start polling in background thread"""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, args=(interval_ms,), daemon=True)
        self._thread.start()
    
    def stop_polling(self):
        """Stop polling"""
        self._running = False
    
    def _poll_loop(self, interval_ms: int):
        """Background polling loop"""
        while self._running:
            if self.retroarch.connected and self.achievements:
                self.check_achievements()
                self.check_collection()
            time.sleep(interval_ms / 1000)


class PokeAchieveGUI:
    """Main GUI Application"""
    
    RARITY_COLORS = {
        "common": "#95a5a6",
        "uncommon": "#2ecc71", 
        "rare": "#3498db",
        "epic": "#9b59b6",
        "legendary": "#f39c12"
    }
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎮 PokeAchieve Tracker v1.2")
        self.root.geometry("900x650")
        self.root.minsize(700, 450)
        
        # Setup paths
        # Handle both regular Python and PyInstaller frozen .exe
        if getattr(sys, 'frozen', False):
            # Running as compiled .exe - look in same directory as .exe
            self.script_dir = Path(sys.executable).parent
        else:
            # Running as Python script
            self.script_dir = Path(__file__).parent
        self.achievements_dir = self.script_dir.parent / "achievements" / "games"
        
        # Debug: Log what paths we're checking
        print(f"DEBUG: script_dir = {self.script_dir}")
        print(f"DEBUG: achievements_dir = {self.achievements_dir}")
        print(f"DEBUG: achievements_dir exists = {self.achievements_dir.exists()}")
        
        # If achievements not found, try same directory (for packaged .exe)
        if not self.achievements_dir.exists():
            self.achievements_dir = self.script_dir / "achievements" / "games"
        self.data_dir = Path.home() / ".pokeachieve"
        self.progress_file = self.data_dir / "progress.json"
        self.config_file = self.data_dir / "config.json"
        self.data_dir.mkdir(exist_ok=True)
        
        # Load config
        self.config = self._load_config()
        
        # Components
        self.retroarch = RetroArchClient()
        self.api = None
        if self.config.get("api_key"):
            self.api = PokeAchieveAPI(
                base_url=self.config.get("api_url", "https://pokeachieve.com/api"),
                api_key=self.config["api_key"]
            )
        self.tracker = AchievementTracker(self.retroarch, self.api)
        
        # State
        self.is_running = False
        self.status_check_interval = 3000
        self.poll_interval = self.config.get("poll_interval", 2000)
        self.api_sync_enabled = self.config.get("api_sync", True)
        
        self._build_ui()
        self._start_status_check()
    
    def _load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass
    
    def _build_ui(self):
        """Build the user interface"""
        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Status Tab
        self.status_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.status_frame, text="📊 Status")
        self._build_status_tab()
        
        # Achievements Tab
        self.achievements_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.achievements_frame, text="🏆 Achievements")
        self._build_achievements_tab()
        
        # Collection Tab (NEW!)
        self.collection_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.collection_frame, text="📱 Collection")
        self._build_collection_tab()
        
        # Log Tab
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="📝 Log")
        self._build_log_tab()
    
    def _build_status_tab(self):
        """Build status tab"""
        # Connection status
        conn_frame = ttk.LabelFrame(self.status_frame, text="Connection Status", padding=10)
        conn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.ra_status_label = ttk.Label(conn_frame, text="RetroArch: Disconnected")
        self.ra_status_label.pack(anchor=tk.W)
        
        self.api_status_label = ttk.Label(conn_frame, text="API: Not configured")
        self.api_status_label.pack(anchor=tk.W)
        
        self.game_label = ttk.Label(conn_frame, text="Game: None")
        self.game_label.pack(anchor=tk.W)
        
        # Progress
        progress_frame = ttk.LabelFrame(self.status_frame, text="Progress", padding=10)
        progress_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.progress_label = ttk.Label(progress_frame, text="0/0 (0%) - 0/0 pts")
        self.progress_label.pack(anchor=tk.W)
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # Collection Summary (NEW!)
        collection_frame = ttk.LabelFrame(self.status_frame, text="Pokemon Collection", padding=10)
        collection_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.collection_label = ttk.Label(collection_frame, text="Caught: 0 | Shiny: 0 | Party: 0")
        self.collection_label.pack(anchor=tk.W)
        
        # Controls
        controls_frame = ttk.Frame(self.status_frame)
        controls_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.start_btn = ttk.Button(controls_frame, text="▶ Start Tracking", command=self._start_tracking)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(controls_frame, text="⏹ Stop", command=self._stop_tracking, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(controls_frame, text="⚙ Settings", command=self._show_settings).pack(side=tk.LEFT, padx=5)
    
    def _build_achievements_tab(self):
        """Build achievements tab"""
        # Recent unlocks
        recent_frame = ttk.LabelFrame(self.achievements_frame, text="Recent Unlocks", padding=10)
        recent_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.recent_list = scrolledtext.ScrolledText(
            recent_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            state='disabled',
            height=10
        )
        self.recent_list.pack(fill=tk.BOTH, expand=True)
    
    def _build_collection_tab(self):
        """Build collection tab (NEW!)"""
        # Party display
        party_frame = ttk.LabelFrame(self.collection_frame, text="Current Party", padding=10)
        party_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.party_display = ttk.Label(party_frame, text="No party data yet - start tracking to see your Pokemon!")
        self.party_display.pack()
        
        # Recent catches
        catches_frame = ttk.LabelFrame(self.collection_frame, text="Recent Catches", padding=10)
        catches_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.catches_list = scrolledtext.ScrolledText(
            catches_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            state='disabled',
            height=10
        )
        self.catches_list.pack(fill=tk.BOTH, expand=True)
    
    def _build_log_tab(self):
        """Build log tab"""
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            state='disabled',
            height=20
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    def _log(self, message: str, level: str = "info"):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "ℹ", "success": "✅", "error": "❌", "unlock": "🏆", "api": "🌐", "collection": "📱"}.get(level, "ℹ")
        
        self.log_text.configure(state='normal')
        self.log_text.insert('end', f"[{timestamp}] {prefix} {message}\n")
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
    
    def _start_status_check(self):
        """Start periodic status check"""
        self._check_status()
    
    def _check_status(self):
        """Check RetroArch connection and game status"""
        # Check RetroArch
        ra_connected = self.retroarch.connected
        if not ra_connected:
            ra_connected = self.retroarch.connect()
        
        if ra_connected:
            self.ra_status_label.configure(text="RetroArch: Connected ✓")
            self._detect_game()
        else:
            self.ra_status_label.configure(text="RetroArch: Disconnected")
        
        # Check API
        if self.api:
            self.api_status_label.configure(text="API: Connected ✓")
        else:
            self.api_status_label.configure(text="API: Not configured")
        
        self.root.after(self.status_check_interval, self._check_status)
    
    def _detect_game(self):
        """Detect which game is loaded"""
        game_name = self.retroarch.get_current_game()
        
        if game_name and game_name != self.tracker.game_name:
            self._log(f"Game detected: {game_name}")
            self._load_game_achievements(game_name)
    
    def _load_game_achievements(self, game_name: str):
        """Load achievements for detected game"""
        # Strip ROM hack suffixes like "(Enhanced)" for matching
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        game_map = {
            "Pokemon Red": "pokemon_red.json",
            "Pokemon Blue": "pokemon_blue.json",
            "Pokemon Gold": "pokemon_gold.json",
            "Pokemon Silver": "pokemon_silver.json",
            "Pokemon Crystal": "pokemon_crystal.json",
            "Pokemon Emerald": "pokemon_emerald.json",
            "Pokemon FireRed": "pokemon_firered.json",
            "Pokemon LeafGreen": "pokemon_leafgreen.json",
            "Pokemon Ruby": "pokemon_ruby.json",
            "Pokemon Sapphire": "pokemon_sapphire.json",
        }
        
        achievement_file = None
        display_name = None
        for key, filename in game_map.items():
            if key.lower() in clean_name.lower():
                achievement_file = self.achievements_dir / filename
                display_name = key
                break
        
        if achievement_file and achievement_file.exists():
            if self.tracker.load_game(display_name, achievement_file):
                self.tracker.load_progress(self.progress_file)
                
                # Merge with website data (fetch latest from server)
                if self.api:
                    self._merge_with_website_data(display_name)
                
                self.game_label.configure(text=f"Game: {display_name}")
                self._log(f"Loaded {len(self.tracker.achievements)} achievements for {display_name}", "success")
                
                if not self.is_running:
                    self._start_tracking()
    
    def _merge_with_website_data(self, game_name: str):
        """Merge local achievements with website data - never removes server achievements"""
        try:
            game_id = self.tracker.GAME_IDS.get(game_name)
            if not game_id:
                return
            
            success, data = self.api.get_progress(game_id)
            if success and data and isinstance(data, dict):
                server_unlocked = set(data.get('unlocked_achievement_ids', []))
                local_unlocked = set(a.id for a in self.tracker.achievements if a.unlocked)
                
                # Merge: take union (never remove)
                all_unlocked = server_unlocked | local_unlocked
                
                # Update local achievements to include server ones
                newly_added = 0
                for ach in self.tracker.achievements:
                    if ach.id in server_unlocked and not ach.unlocked:
                        ach.unlocked = True
                        ach.unlocked_at = datetime.now()
                        newly_added += 1
                
                if newly_added > 0:
                    self._log(f"Synced {newly_added} achievements from website", "info")
                    self.tracker.save_progress(self.progress_file)
        except Exception as e:
            self._log(f"Could not sync with website: {e}", "warning")
        else:
            self.game_label.configure(text=f"Game: {game_name} (No achievements)")
    
    def _start_tracking(self):
        """Start achievement and collection tracking"""
        if not self.retroarch.connected:
            messagebox.showwarning("Not Connected", "Not connected to RetroArch.")
            return
        
        if not self.tracker.achievements and not self.tracker.game_name:
            messagebox.showwarning("No Game", "No game loaded. Load a Pokemon ROM in RetroArch first.")
            return
        
        self.is_running = True
        self.tracker.start_polling(self.poll_interval)
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self._log("Tracking started - Monitoring achievements and Pokemon collection", "success")
        
        # Start processing queues
        self._check_unlocks()
        self._process_api_queue()
        self._process_collection_updates()
    
    def _stop_tracking(self):
        """Stop tracking"""
        self.is_running = False
        self.tracker.stop_polling()
        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self._log("Tracking stopped")
        self.tracker.save_progress(self.progress_file)
    
    def _check_unlocks(self):
        """Check for new unlocks"""
        if not self.is_running:
            return
        
        # Process unlock queue
        while not self.tracker._unlock_queue.empty():
            try:
                achievement = self.tracker._unlock_queue.get_nowait()
                self._on_achievement_unlock(achievement)
            except queue.Empty:
                break
        
        # Update progress
        self._update_progress()
        
        self.root.after(2000, self._check_unlocks)
    
    def _process_api_queue(self):
        """Process API post queue"""
        if not self.is_running:
            return
        
        if self.api and self.config.get("api_sync", True):
            while not self.tracker._api_queue.empty():
                try:
                    item = self.tracker._api_queue.get_nowait()
                    
                    if item["type"] == "achievement":
                        ach = item["achievement"]
                        def post_ach(a=ach):
                            success, data = self.api.post_unlock(self.tracker.game_id, a.id)
                            if success:
                                self._log(f"Posted unlock to platform: {a.name}", "api")
                            else:
                                self._log(f"Failed to post unlock: {data.get('error', 'Unknown error')}", "error")
                        threading.Thread(target=post_ach, daemon=True).start()
                    
                    elif item["type"] == "collection":
                        catches = item["catches"]
                        party = item["party"]
                        game = item["game"]
                        def post_collection():
                            self._sync_collection_to_api(catches, party, game)
                        threading.Thread(target=post_collection, daemon=True).start()
                    
                except queue.Empty:
                    break
        
        self.root.after(3000, self._process_api_queue)
    
    def _process_collection_updates(self):
        """Process collection updates from memory reading"""
        if not self.is_running:
            return
        
        while not self.tracker._collection_queue.empty():
            try:
                update = self.tracker._collection_queue.get_nowait()
                catches = update["catches"]
                party = update["party"]
                game = update["game"]
                
                # Log new catches
                for pokemon_id in catches:
                    pokemon_name = self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
                    self._log(f"NEW CATCH: {pokemon_name} (#{pokemon_id})", "collection")
                    self._add_catch_to_list(pokemon_id, game)
                
                # Update party display
                self._update_party_display(party, game)
                
                # Post to API
                if self.api:
                    self.tracker.post_collection_to_platform(catches, party, game)
                
            except queue.Empty:
                break
        
        self.root.after(2000, self._process_collection_updates)
    
    def _sync_collection_to_api(self, catches: List[int], party: List[Dict], game: str):
        """Sync collection data to PokeAchieve API"""
        print(f"[COLLECTION SYNC] Starting sync for {len(catches)} catches, {len(party)} party members")
        
        if not catches and not party:
            print("[COLLECTION SYNC] Nothing to sync")
            return
        
        # Build batch update for new catches
        batch = []
        for pokemon_id in catches:
            entry = {
                "pokemon_id": pokemon_id,
                "pokemon_name": self._get_pokemon_name(pokemon_id),
                "caught": True,
                "shiny": False,
                "game": game
            }
            batch.append(entry)
            print(f"[COLLECTION SYNC] Adding to batch: {entry}")
        
        if batch:
            print(f"[COLLECTION SYNC] Sending batch of {len(batch)} to API...")
            success, data = self.api.post_collection_batch(batch)
            if success:
                self._log(f"Synced {len(batch)} Pokemon to collection", "api")
                print(f"[COLLECTION SYNC] Success: {data}")
            else:
                error_msg = data.get('error', 'Unknown error')
                self._log(f"Failed to sync collection: {error_msg}", "error")
                print(f"[COLLECTION SYNC] Failed: {error_msg}")
        
        # Update party
        for member in party:
            print(f"[COLLECTION SYNC] Updating party slot {member.get('slot')}: Pokemon {member['id']}")
            success, data = self.api.post_party_update(
                member["id"],
                True,
                member.get("slot")
            )
            if success:
                self._log(f"Updated party: {member['id']} in slot {member.get('slot')}", "api")
            else:
                error_msg = data.get('error', 'Unknown error')
                self._log(f"Failed to update party: {error_msg}", "error")
    
    def _get_pokemon_name(self, pokemon_id: int) -> str:
        """Get Pokemon name from ID"""
        if self.tracker and self.tracker.pokemon_reader:
            return self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
        return f"Pokemon #{pokemon_id}"
    
    def _add_catch_to_list(self, pokemon_id: int, game: str = ""):
        """Add catch to recent catches list"""
        pokemon_name = self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
        self.catches_list.configure(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        game_info = f" [{game}]" if game else ""
        self.catches_list.insert('1.0', f"[{timestamp}] ✓ Caught {pokemon_name} (#{pokemon_id}){game_info}!\n")
        self.catches_list.configure(state='disabled')
    
    def _update_party_display(self, party: List[Dict], game: str = ""):
        """Update party display in collection tab"""
        if not party:
            self.party_display.configure(text="Party is empty - Start tracking to see your Pokemon!")
            return
        
        # Build party text with Pokemon names
        party_lines = []
        for p in party:
            name = self.tracker.pokemon_reader.get_pokemon_name(p['id'])
            level_str = f" Lv.{p['level']}" if p.get('level') else ""
            party_lines.append(f"Slot {p['slot']}: {name}{level_str}")
        
        party_text = "\n".join(party_lines)
        self.party_display.configure(text=party_text)
        
        # Update collection summary with game info
        game_info = f" [{game}]" if game else ""
        self.collection_label.configure(
            text=f"Party: {len(party)}/6 Pokemon{game_info}"
        )
    
    def _on_achievement_unlock(self, achievement: Achievement):
        """Handle achievement unlock"""
        self._log(f"UNLOCKED: {achievement.name} (+{achievement.points} pts)", "unlock")
        
        self.recent_list.configure(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        rarity_emoji = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟠"}.get(achievement.rarity, "⚪")
        
        self.recent_list.insert('1.0', f"[{timestamp}] {rarity_emoji} {achievement.name}\n")
        self.recent_list.configure(state='disabled')
        
        self.tracker.save_progress(self.progress_file)
        
        try:
            self.root.bell()
        except:
            pass
    
    def _update_progress(self):
        """Update progress display"""
        progress = self.tracker.get_progress()
        self.progress_label.configure(
            text=f"{progress['unlocked']}/{progress['total']} ({progress['percentage']:.1f}%) - {progress['points']}/{progress['total_points']} pts"
        )
        self.progress_bar['value'] = progress['percentage']
    
    def _show_settings(self):
        """Show settings dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # API Settings
        api_frame = ttk.LabelFrame(dialog, text="PokeAchieve API", padding="10")
        api_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        api_frame.columnconfigure(1, weight=1)
        
        ttk.Label(api_frame, text="Platform URL:").grid(row=0, column=0, sticky="w", pady=5)
        url_entry = ttk.Entry(api_frame)
        url_entry.insert(0, self.config.get("api_url", "https://pokeachieve.com/api"))
        url_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        ttk.Label(api_frame, text="API Key:").grid(row=1, column=0, sticky="w", pady=5)
        key_entry = ttk.Entry(api_frame, show="*")
        key_entry.insert(0, self.config.get("api_key", ""))
        key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        def test_api():
            test_api = PokeAchieveAPI(url_entry.get(), key_entry.get())
            success, message = test_api.test_auth()
            if success:
                messagebox.showinfo("Success", f"API connection successful!\n{message}")
            else:
                messagebox.showerror("Failed", f"API connection failed:\n{message}")
        
        ttk.Button(api_frame, text="Test Connection", command=test_api).grid(row=2, column=0, columnspan=2, pady=10)
        
        def save():
            self.config["api_url"] = url_entry.get()
            self.config["api_key"] = key_entry.get()
            
            if self.config["api_key"]:
                self.api = PokeAchieveAPI(self.config["api_url"], self.config["api_key"])
                self.tracker.api = self.api
            
            self._save_config()
            self._log("Settings saved")
            dialog.destroy()
            self._test_api_connection()
        
        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=0, pady=10)
        
        dialog.columnconfigure(0, weight=1)
    
    def _test_api_connection(self):
        """Test API connection"""
        if self.api:
            def test():
                success, message = self.api.test_auth()
                if success:
                    self.api_status_label.configure(text="API: Connected ✓")
                    self._log("API authentication successful", "success")
                else:
                    self.api_status_label.configure(text="API: Failed")
                    self._log(f"API authentication failed: {message}", "error")
            
            threading.Thread(target=test, daemon=True).start()
    
    def run(self):
        """Start the application"""
        self.root.mainloop()


def main():
    """Entry point"""
    app = PokeAchieveGUI()
    app.run()


if __name__ == "__main__":
    main()
