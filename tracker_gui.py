"""
PokeAchieve Tracker - Cross-Platform GUI with API Integration
Connects to RetroArch and syncs achievements + Pokemon collection to PokeAchieve platform
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog
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
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
from hashlib import sha256
from dataclasses import dataclass, asdict

LOGGER = logging.getLogger("pokeachieve_tracker")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)


def log_event(level: int, event: str, **fields):
    """Structured logging helper."""
    if fields:
        LOGGER.log(level, "%s %s", event, json.dumps(fields, default=str, sort_keys=True))
    else:
        LOGGER.log(level, "%s", event)

# Import game configuration system
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from game_configs import (
        get_game_config, get_generation, get_platform,
        DerivedAchievementChecker
    )
    GAME_CONFIGS_AVAILABLE = True
except ImportError:
    GAME_CONFIGS_AVAILABLE = False
    LOGGER.warning("game_configs_unavailable using legacy hardcoded addresses")


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
    
    def __init__(self, base_url: str = "https://pokeachieve.com", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip() if api_key else ""
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "PokeAchieveTracker/1.0"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def _make_url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"{self.base_url}{endpoint}"
    
    def _request(self, method: str, endpoint: str, data: dict = None) -> tuple[bool, dict]:
        """Make API request and return (success, response_data)"""
        url = self._make_url(endpoint)
        log_event(logging.INFO, "api_request", method=method, url=url)
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
                log_event(logging.INFO, "api_success", method=method, endpoint=endpoint, status=status)
                return True, json.loads(body)
        except urllib.error.HTTPError as e:
            status = e.getcode()
            error_body = e.read().decode()
            log_event(logging.ERROR, "api_http_error", method=method, endpoint=endpoint, status=status, body_preview=error_body[:200])
            try:
                error_data = json.loads(error_body)
                return False, {"error": error_data.get("detail", str(e)), "status": status}
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False, {"error": f"HTTP {status}: {error_body[:200]}", "status": status}
        except Exception as e:
            log_event(logging.ERROR, "api_exception", method=method, endpoint=endpoint, error_type=type(e).__name__, error=str(e))
            return False, {"error": str(e)}
    
    def _extract_unlocked_ids(self, data: object, game_id: int) -> List[str]:
        """Normalize different progress response shapes into comparable unlock keys."""
        if isinstance(data, dict):
            if isinstance(data.get("unlocked_achievement_ids"), list):
                return [str(x) for x in data.get("unlocked_achievement_ids", [])]

            achievements = data.get("achievements")
            if isinstance(achievements, list):
                return [
                    str(a.get("id") or a.get("achievement_id"))
                    for a in achievements
                    if isinstance(a, dict) and a.get("unlocked") and (a.get("id") or a.get("achievement_id"))
                ]

        if isinstance(data, list):
            unlocked: List[str] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("game_id") not in (None, game_id):
                    continue
                if item.get("unlocked") or item.get("is_unlocked") or item.get("status") == "unlocked":
                    ach_id = item.get("id") or item.get("achievement_id")
                    if ach_id is not None:
                        unlocked.append(str(ach_id))

                    nested = item.get("achievement") if isinstance(item.get("achievement"), dict) else {}
                    ach_name = nested.get("name") or item.get("achievement_name")
                    if isinstance(ach_name, str) and ach_name.strip():
                        unlocked.append(f"name:{ach_name.strip().lower()}")
            return unlocked

        return []

    def _resolve_achievement_id(self, game_id: int, achievement_name: Optional[str]) -> Optional[int]:
        """Resolve numeric achievement ID required by live API using the user's achievement list."""
        if not achievement_name:
            return None

        endpoints = ("/api/users/me/achievements", "/users/me/achievements")
        target = achievement_name.strip().lower()
        for endpoint in endpoints:
            success, data = self._request("GET", endpoint)
            if not success or not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("game_id") not in (None, game_id):
                    continue
                nested = item.get("achievement") if isinstance(item.get("achievement"), dict) else {}
                ach_name = nested.get("name") or item.get("achievement_name")
                ach_id = nested.get("id") or item.get("achievement_id") or item.get("id")
                if isinstance(ach_name, str) and ach_name.strip().lower() == target and ach_id is not None:
                    try:
                        return int(ach_id)
                    except (TypeError, ValueError):
                        continue
        return None

    def test_auth(self) -> tuple[bool, str]:
        """Test API key authentication against authenticated user profile endpoint"""
        success, data = self._request("GET", "/api/users/me")
        if not success:
            success, data = self._request("GET", "/users/me")

        if success:
            username = data.get("username") if isinstance(data, dict) else None
            return True, f"Authenticated as {username}" if username else "Authentication successful"
        return False, data.get("error", "Authentication failed")
    
    def get_progress(self, game_id: int) -> tuple[bool, list]:
        """Get user's progress for a game"""
        success, data = self._request("GET", f"/api/tracker/progress/{game_id}")
        if not success:
            # Backwards compatibility with legacy backend route
            success, data = self._request("GET", "/users/me/achievements")
        if success:
            return True, data.get("unlocked_achievement_ids", [])
        return False, []
    
    def post_unlock(self, game_id: int, achievement_id: str, achievement_name: Optional[str] = None) -> tuple[bool, dict]:
        """Post achievement unlock to platform"""
        live_achievement_id: object = achievement_id
        if isinstance(achievement_id, str) and not achievement_id.isdigit():
            resolved = self._resolve_achievement_id(game_id, achievement_name)
            if resolved is not None:
                live_achievement_id = resolved

        payload = {
            "game_id": game_id,
            "achievement_id": live_achievement_id,
            "current_value": 1,
            "unlocked": True,
        }
        success, data = self._request("POST", "/api/tracker/unlock", payload)
        if not success:
            # Backwards compatibility with legacy backend route
            legacy_payload = {
                "game_id": game_id,
                "achievement_id": achievement_id,
                "achievement_name": achievement_name,
                "unlocked_at": datetime.now().isoformat()
            }
            return self._request("POST", "/progress/update", legacy_payload)
        return success, data
    
    # Pokemon Collection API Methods
    def post_collection_batch(self, pokemon_list: List[Dict]) -> tuple[bool, dict]:
        """Post batch of Pokemon collection updates"""
        success, data = self._request("POST", "/api/collection/batch-update", pokemon_list)
        if not success:
            # Backwards compatibility with legacy backend route
            return self._request("POST", "/collection/batch-update", pokemon_list)
        return success, data

    def start_session(self, game_id: int) -> tuple[bool, dict]:
        return self._request("POST", "/api/sessions/start", {"game_id": game_id})
    
    def post_party_update(self, pokemon_id: int, in_party: bool, party_slot: int = None) -> tuple[bool, dict]:
        """Update party status for a Pokemon"""
        payload = {
            "pokemon_id": pokemon_id,
            "in_party": in_party,
            "party_slot": party_slot
        }
        success, data = self._request("POST", "/api/collection/party", payload)
        if not success:
            # Backwards compatibility with legacy backend route
            return self._request("POST", "/collection/party", payload)
        return success, data

    def get_collection(self) -> tuple[bool, dict]:
        """Get tracker-style collection summary (total_caught, total_shiny, completion_percentage, collection, party)"""
        success, data = self._request("GET", "/api/collection")
        if success:
            return True, data
        return False, data

    def post_collection_update(self, pokemon_data: Dict) -> tuple[bool, dict]:
        """Update a single Pokemon entry (supports caught_at parsing)"""
        success, data = self._request("POST", "/api/collection/update", pokemon_data)
        if not success:
            # Backwards compatibility with legacy backend route
            return self._request("POST", "/collection/update", pokemon_data)
        return success, data


class RetroArchClient:
    """Client for connecting to RetroArch network command interface"""
    
    GAME_ALIASES: Dict[str, str] = {
        "pokemon red": "Pokemon Red",
        "pokemon blue": "Pokemon Blue",
        "pokemon yellow": "Pokemon Yellow",
        "pokemon gold": "Pokemon Gold",
        "pokemon silver": "Pokemon Silver",
        "pokemon crystal": "Pokemon Crystal",
        "pokemon ruby": "Pokemon Ruby",
        "pokemon sapphire": "Pokemon Sapphire",
        "pokemon emerald": "Pokemon Emerald",
        "pokemon firered": "Pokemon FireRed",
        "pokemon fire red": "Pokemon FireRed",
        "pokemon leafgreen": "Pokemon LeafGreen",
        "pokemon leaf green": "Pokemon LeafGreen",
    }
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
                except OSError:
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
    
    def _normalize_game_name(self, raw_text: str) -> Optional[str]:
        normalized = re.sub(r"[^a-z0-9]+", " ", raw_text.lower()).strip()
        for alias, canonical in self.GAME_ALIASES.items():
            if alias in normalized:
                return canonical
        return None

    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        print(f"[DEBUG] RetroArch GET_STATUS response: {response}")
        if response:
            normalized = self._normalize_game_name(response)
            if normalized:
                print(f"[DEBUG] Normalized game from status: {normalized}")
                return normalized

        if response and response.startswith("GET_STATUS"):
            # Parse: GET_STATUS PAUSED game_boy,Pokemon Red(Enhanced),crc32=...
            # Handle game names with commas like "Pokemon - Emerald Version (USA, Europe)"
            try:
                # Remove GET_STATUS prefix
                rest = response.replace("GET_STATUS ", "")
                # Split by crc32= to get the part before it
                if ",crc32=" in rest:
                    before_crc = rest.split(",crc32=")[0]
                else:
                    before_crc = rest
                # Now split by first comma to get platform and game name
                if "," in before_crc:
                    platform, game_name = before_crc.split(",", 1)
                    game_name = game_name.strip()
                    # Clean up game name parsing
                    game_name = re.sub(r"\s*Playing", "", game_name)
                    game_name = re.sub(r"\s*\(USA, Europe\)", "", game_name)
                    game_name = re.sub(r" - (.*) Version", r" \1", game_name)
                    game_name = game_name.strip()
                    normalized = self._normalize_game_name(game_name)
                    if normalized:
                        print(f"[DEBUG] Detected game: {normalized}")
                        return normalized
                    print(f"[DEBUG] Detected game (raw): {game_name}")
                    return game_name
            except Exception as e:
                log_event(logging.WARNING, "game_parse_error", error=str(e))
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
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024284",
            "party_slot_size": 100,
        },
        "pokemon_sapphire": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024284",
            "party_slot_size": 100,
        },
        "pokemon_emerald": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024284",
            "party_slot_size": 100,
        },
        "pokemon_firered": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024284",
            "party_slot_size": 100,
        },
        "pokemon_leafgreen": {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024284",
            "party_slot_size": 100,
        },
    }
    
    # Pokemon names lookup (Gen 1-3)
    POKEMON_NAMES = {
        # Generation 1 (1-151)
        1: "Bulbasaur", 2: "Ivysaur", 3: "Venusaur",
        4: "Charmander", 5: "Charmeleon", 6: "Charizard",
        7: "Squirtle", 8: "Wartortle", 9: "Blastoise",
        10: "Caterpie", 11: "Metapod", 12: "Butterfree",
        13: "Weedle", 14: "Kakuna", 15: "Beedrill",
        16: "Pidgey", 17: "Pidgeotto", 18: "Pidgeot",
        19: "Rattata", 20: "Raticate",
        21: "Spearow", 22: "Fearow",
        23: "Ekans", 24: "Arbok",
        25: "Pikachu", 26: "Raichu",
        27: "Sandshrew", 28: "Sandslash",
        29: "Nidoran♀", 30: "Nidorina", 31: "Nidoqueen",
        32: "Nidoran♂", 33: "Nidorino", 34: "Nidoking",
        35: "Clefairy", 36: "Clefable",
        37: "Vulpix", 38: "Ninetales",
        39: "Jigglypuff", 40: "Wigglytuff",
        41: "Zubat", 42: "Golbat",
        43: "Oddish", 44: "Gloom", 45: "Vileplume",
        46: "Paras", 47: "Parasect",
        48: "Venonat", 49: "Venomoth",
        50: "Diglett", 51: "Dugtrio",
        52: "Meowth", 53: "Persian",
        54: "Psyduck", 55: "Golduck",
        56: "Mankey", 57: "Primeape",
        58: "Growlithe", 59: "Arcanine",
        60: "Poliwag", 61: "Poliwhirl", 62: "Poliwrath",
        63: "Abra", 64: "Kadabra", 65: "Alakazam",
        66: "Machop", 67: "Machoke", 68: "Machamp",
        69: "Bellsprout", 70: "Weepinbell", 71: "Victreebel",
        72: "Tentacool", 73: "Tentacruel",
        74: "Geodude", 75: "Graveler", 76: "Golem",
        77: "Ponyta", 78: "Rapidash",
        79: "Slowpoke", 80: "Slowbro",
        81: "Magnemite", 82: "Magneton",
        83: "Farfetch'd",
        84: "Doduo", 85: "Dodrio",
        86: "Seel", 87: "Dewgong",
        88: "Grimer", 89: "Muk",
        90: "Shellder", 91: "Cloyster",
        92: "Gastly", 93: "Haunter", 94: "Gengar",
        95: "Onix",
        96: "Drowzee", 97: "Hypno",
        98: "Krabby", 99: "Kingler",
        100: "Voltorb", 101: "Electrode",
        102: "Exeggcute", 103: "Exeggutor",
        104: "Cubone", 105: "Marowak",
        106: "Hitmonlee", 107: "Hitmonchan",
        108: "Lickitung",
        109: "Koffing", 110: "Weezing",
        111: "Rhyhorn", 112: "Rhydon",
        113: "Chansey",
        114: "Tangela",
        115: "Kangaskhan",
        116: "Horsea", 117: "Seadra",
        118: "Goldeen", 119: "Seaking",
        120: "Staryu", 121: "Starmie",
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
        137: "Porygon",
        138: "Omanyte", 139: "Omastar",
        140: "Kabuto", 141: "Kabutops",
        142: "Aerodactyl",
        143: "Snorlax",
        144: "Articuno", 145: "Zapdos", 146: "Moltres",
        147: "Dratini", 148: "Dragonair", 149: "Dragonite",
        150: "Mewtwo", 151: "Mew",
        # Generation 2 (152-251)
        152: "Chikorita", 153: "Bayleef", 154: "Meganium",
        155: "Cyndaquil", 156: "Quilava", 157: "Typhlosion",
        158: "Totodile", 159: "Croconaw", 160: "Feraligatr",
        161: "Sentret", 162: "Furret",
        163: "Hoothoot", 164: "Noctowl",
        165: "Ledyba", 166: "Ledian",
        167: "Spinarak", 168: "Ariados",
        169: "Crobat",
        170: "Chinchou", 171: "Lanturn",
        172: "Pichu",
        173: "Cleffa",
        174: "Igglybuff",
        175: "Togepi", 176: "Togetic",
        177: "Natu", 178: "Xatu",
        179: "Mareep", 180: "Flaaffy", 181: "Ampharos",
        182: "Bellossom",
        183: "Marill", 184: "Azumarill",
        185: "Sudowoodo",
        186: "Politoed",
        187: "Hoppip", 188: "Skiploom", 189: "Jumpluff",
        190: "Aipom",
        191: "Sunkern", 192: "Sunflora",
        193: "Yanma",
        194: "Wooper", 195: "Quagsire",
        196: "Espeon", 197: "Umbreon",
        198: "Murkrow",
        199: "Slowking",
        200: "Misdreavus",
        201: "Unown",
        202: "Wobbuffet",
        203: "Girafarig",
        204: "Pineco", 205: "Forretress",
        206: "Dunsparce",
        207: "Gligar",
        208: "Steelix",
        209: "Snubbull", 210: "Granbull",
        211: "Qwilfish",
        212: "Scizor",
        213: "Shuckle",
        214: "Heracross",
        215: "Sneasel",
        216: "Teddiursa", 217: "Ursaring",
        218: "Slugma", 219: "Magcargo",
        220: "Swinub", 221: "Piloswine",
        222: "Corsola",
        223: "Remoraid", 224: "Octillery",
        225: "Delibird",
        226: "Mantine",
        227: "Skarmory",
        228: "Houndour", 229: "Houndoom",
        230: "Kingdra",
        231: "Phanpy", 232: "Donphan",
        233: "Porygon2",
        234: "Stantler",
        235: "Smeargle",
        236: "Tyrogue", 237: "Hitmontop",
        238: "Smoochum",
        239: "Elekid",
        240: "Magby",
        241: "Miltank",
        242: "Blissey",
        243: "Raikou", 244: "Entei", 245: "Suicune",
        246: "Larvitar", 247: "Pupitar", 248: "Tyranitar",
        249: "Lugia", 250: "Ho-Oh", 251: "Celebi",
        # Generation 3 (252-386)
        252: "Treecko", 253: "Grovyle", 254: "Sceptile",
        255: "Torchic", 256: "Combusken", 257: "Blaziken",
        258: "Mudkip", 259: "Marshtomp", 260: "Swampert",
        261: "Poochyena", 262: "Mightyena",
        263: "Zigzagoon", 264: "Linoone",
        265: "Wurmple", 266: "Silcoon", 267: "Beautifly",
        268: "Cascoon", 269: "Dustox",
        270: "Lotad", 271: "Lombre", 272: "Ludicolo",
        273: "Seedot", 274: "Nuzleaf", 275: "Shiftry",
        276: "Taillow", 277: "Swellow",
        278: "Wingull", 279: "Pelipper",
        280: "Ralts", 281: "Kirlia", 282: "Gardevoir",
        283: "Surskit", 284: "Masquerain",
        285: "Shroomish", 286: "Breloom",
        287: "Slakoth", 288: "Vigoroth", 289: "Slaking",
        290: "Nincada", 291: "Ninjask", 292: "Shedinja",
        293: "Whismur", 294: "Loudred", 295: "Exploud",
        296: "Makuhita", 297: "Hariyama",
        298: "Azurill",
        299: "Nosepass",
        300: "Skitty", 301: "Delcatty",
        302: "Sableye",
        303: "Mawile",
        304: "Aron", 305: "Lairon", 306: "Aggron",
        307: "Meditite", 308: "Medicham",
        309: "Electrike", 310: "Manectric",
        311: "Plusle",
        312: "Minun",
        313: "Volbeat",
        314: "Illumise",
        315: "Roselia",
        316: "Gulpin", 317: "Swalot",
        318: "Carvanha", 319: "Sharpedo",
        320: "Wailmer", 321: "Wailord",
        322: "Numel", 323: "Camerupt",
        324: "Torkoal",
        325: "Spoink", 326: "Grumpig",
        327: "Spinda",
        328: "Trapinch", 329: "Vibrava", 330: "Flygon",
        331: "Cacnea", 332: "Cacturne",
        333: "Swablu", 334: "Altaria",
        335: "Zangoose",
        336: "Seviper",
        337: "Lunatone",
        338: "Solrock",
        339: "Barboach", 340: "Whiscash",
        341: "Corphish", 342: "Crawdaunt",
        343: "Baltoy", 344: "Claydol",
        345: "Lileep", 346: "Cradily",
        347: "Anorith", 348: "Armaldo",
        349: "Feebas", 350: "Milotic",
        351: "Castform",
        352: "Kecleon",
        353: "Shuppet", 354: "Banette",
        355: "Duskull", 356: "Dusclops",
        357: "Tropius",
        358: "Chimecho",
        359: "Absol",
        360: "Wynaut",
        361: "Snorunt", 362: "Glalie",
        363: "Spheal", 364: "Sealeo", 365: "Walrein",
        366: "Clamperl", 367: "Huntail", 368: "Gorebyss",
        369: "Relicanth",
        370: "Luvdisc",
        371: "Bagon", 372: "Shelgon", 373: "Salamence",
        374: "Beldum", 375: "Metang", 376: "Metagross",
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
        """Get memory addresses for current game - uses game_configs when available"""
        # Strip ROM hack suffixes like "(Enhanced)", "(U)", etc.
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        game_key = clean_name.lower().replace(" ", "_").replace("'", "").strip()
        
        # Try new game_configs system first
        if GAME_CONFIGS_AVAILABLE:
            config = get_game_config(clean_name)
            if config:
                return {
                    "gen": config.generation,
                    "max_pokemon": config.max_pokemon,
                    "pokedex_caught": config.pokedex_caught_start,
                    "pokedex_seen": config.pokedex_seen_start,
                    "party_count": config.party_count_address,
                    "party_start": config.party_start_address,
                    "party_slot_size": config.party_slot_size,
                    "badge_address": config.badge_address,
                }
        
        # Fallback to legacy hardcoded addresses
        return self.GAME_ADDRESSES.get(game_key)
    
    def validate_memory_profile(self, game_name: str) -> Dict[str, object]:
        """Validate key memory addresses for the selected game."""
        config = self.get_game_config(game_name)
        if not config:
            return {"ok": False, "reason": "missing_config"}

        checks = {
            "pokedex_caught": config.get("pokedex_caught"),
            "party_count": config.get("party_count"),
        }
        failures = []
        for key, addr in checks.items():
            if not addr:
                failures.append(f"{key}:missing")
                continue
            value = self.retroarch.read_memory(addr)
            if value is None:
                failures.append(f"{key}:unreadable")

        return {"ok": len(failures) == 0, "failures": failures, "checks": checks}

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
        self._collection_baseline_initialized = False
        self._unlock_streaks: Dict[str, int] = {}
        self._bad_read_streak = 0
        self._derived_checker: Optional[DerivedAchievementChecker] = None
    
    def _get_validation_profile(self) -> Dict[str, int]:
        """Per-game validation thresholds used for read-confidence checks."""
        gen = 1
        if self.game_name and self.pokemon_reader:
            cfg = self.pokemon_reader.get_game_config(self.game_name)
            if cfg:
                gen = int(cfg.get("gen", 1))

        by_gen = {
            1: {"max_unlocks_per_poll": 3, "max_new_catches_per_poll": 5},
            2: {"max_unlocks_per_poll": 3, "max_new_catches_per_poll": 5},
            3: {"max_unlocks_per_poll": 4, "max_new_catches_per_poll": 6},
        }
        return by_gen.get(gen, by_gen[1])

    def _handle_bad_read(self, reason: str):
        """Track repeated suspicious reads and attempt lightweight auto-recovery."""
        self._bad_read_streak += 1
        log_event(logging.WARNING, "memory_read_suspicious", game=self.game_name, reason=reason, streak=self._bad_read_streak)
        if self._bad_read_streak >= 3:
            log_event(logging.WARNING, "memory_read_reconnect", game=self.game_name)
            self.retroarch.disconnect()
            self.retroarch.connect()
            self._bad_read_streak = 0

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
            self._last_party = []
            self._last_pokedex = []
            self._collection_baseline_initialized = False
            self._unlock_streaks = {}
            self._bad_read_streak = 0

            validation = self.pokemon_reader.validate_memory_profile(game_name)
            log_event(logging.INFO, "memory_profile_validation", game=game_name, ok=validation.get("ok"), failures=validation.get("failures", []))

            # Initialize derived achievement checker
            if GAME_CONFIGS_AVAILABLE and self.game_name:
                try:
                    self._derived_checker = DerivedAchievementChecker(self.retroarch, self.game_name)
                except ValueError:
                    self._derived_checker = None
            
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
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log_event(logging.WARNING, "progress_load_failed", file=str(progress_file), error=str(exc))

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
        except OSError as exc:
            log_event(logging.WARNING, "progress_save_failed", file=str(progress_file), error=str(exc))

    def sync_with_platform(self) -> tuple[int, int]:
        """Sync progress with platform. Returns (newly_synced, errors)"""
        if not self.api or not self.game_id:
            return 0, 0
        
        success, unlocked_ids = self.api.get_progress(self.game_id)
        if not success:
            return 0, 1
        
        newly_synced = 0
        unlocked_set = set(str(x) for x in unlocked_ids)
        for ach in self.achievements:
            by_id = ach.id in unlocked_set
            by_name = f"name:{ach.name.strip().lower()}" in unlocked_set
            if (by_id or by_name) and not ach.unlocked:
                ach.unlocked = True
                newly_synced += 1
        
        return newly_synced, 0
    
    def check_achievements(self) -> List[Achievement]:
        """Check all achievements, return newly unlocked ones"""
        newly_unlocked = []
        profile = self._get_validation_profile()
        candidates_this_poll = 0

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
                candidates_this_poll += 1
                if candidates_this_poll > profile["max_unlocks_per_poll"]:
                    log_event(logging.WARNING, "unlock_spike_ignored", game=self.game_name, candidates=candidates_this_poll, threshold=profile["max_unlocks_per_poll"])
                    self._unlock_streaks[achievement.id] = 0
                    continue
                self._unlock_streaks[achievement.id] = self._unlock_streaks.get(achievement.id, 0) + 1
                # Require two consecutive positive polls to avoid transient memory-read false positives.
                if self._unlock_streaks[achievement.id] >= 2:
                    achievement.unlocked = True
                    achievement.unlocked_at = datetime.now().isoformat()
                    newly_unlocked.append(achievement)
                    self._unlock_queue.put(achievement)
                    self.post_unlock_to_platform(achievement)
            else:
                self._unlock_streaks[achievement.id] = 0
        
        return newly_unlocked
    
    def _check_derived_achievement(self, achievement: Achievement) -> bool:
        """Check achievements that require calculation from multiple memory locations"""
        # Use new game_configs system if available
        if GAME_CONFIGS_AVAILABLE and self._derived_checker:
            return self._check_derived_with_config(achievement)
        
        # Fall back to legacy hardcoded checks (Gen 1 only)
        return self._check_derived_legacy(achievement)
    
    def _check_derived_with_config(self, achievement: Achievement) -> bool:
        """Check derived achievements using game_configs system"""
        if not self._derived_checker:
            return False
        
        ach_id = achievement.id.lower()
        
        # Pokedex count achievements
        if "pokedex" in ach_id and not ach_id.endswith("_complete") and not ach_id.endswith("_master"):
            caught_count = self._derived_checker.get_caught_count()
            if "_pokedex_10" in ach_id:
                return caught_count >= 10
            elif "_pokedex_25" in ach_id:
                return caught_count >= 25
            elif "_pokedex_50" in ach_id:
                return caught_count >= 50
            elif "_pokedex_100" in ach_id:
                return caught_count >= 100
            elif "_pokedex_150" in ach_id or "_pokedex_200" in ach_id:
                config = get_game_config(self.game_name) if GAME_CONFIGS_AVAILABLE else None
                max_pokemon = config.max_pokemon if config else 150
                return caught_count >= max_pokemon
            elif "_pokedex_151" in ach_id or "_pokedex_251" in ach_id or "_pokedex_386" in ach_id:
                config = get_game_config(self.game_name) if GAME_CONFIGS_AVAILABLE else None
                max_pokemon = config.max_pokemon if config else 151
                return caught_count >= max_pokemon
        
        # All gyms
        if ach_id.endswith("_gym_all"):
            return self._derived_checker.check_all_badges()
        
        # Elite Four members
        if "elite_four" in ach_id and not ach_id.endswith("_all"):
            # Extract member name from achievement ID
            for member in ["lorelei", "bruno", "agatha", "lance", "will", "koga", "karen", 
                          "sidney", "phoebe", "glacia", "drake"]:
                if member in ach_id:
                    return self._derived_checker.check_elite_four_member(member)
            return False
        
        # All Elite Four
        if ach_id.endswith("_elite_four_all"):
            return self._derived_checker.check_all_elite_four()
        
        # Legendary individual
        if "legendary" in ach_id:
            for legendary in ["mewtwo", "moltres", "zapdos", "articuno", "mew",
                             "raikou", "entei", "suicune", "lugia", "ho-oh", "celebi",
                             "regirock", "regice", "registeel", "latias", "latios",
                             "kyogre", "groudon", "rayquaza", "jirachi", "deoxys"]:
                if legendary in ach_id:
                    return self._derived_checker.check_legendary_caught(legendary)
        
        # All legendary birds (Gen 1 only)
        if ach_id.endswith("_legendary_birds"):
            return self._derived_checker.check_all_legendary_birds()
        
        # All legendaries
        if ach_id.endswith("_legendary_all"):
            return self._derived_checker.check_all_legendaries()
        
        # First steps
        if "first_steps" in ach_id:
            return self._derived_checker.check_first_steps()
        
        # Story achievements - HM detection
        if "_story_hm_" in ach_id:
            hm_map = {
                "cut": "cut",
                "fly": "fly", 
                "surf": "surf",
                "strength": "strength",
                "flash": "flash",
            }
            for hm_key, hm_name in hm_map.items():
                if f"_story_hm_{hm_key}" in ach_id:
                    return self._derived_checker.check_has_hm(hm_name)
        
        # Pokemon Master
        if ach_id.endswith("_pokemon_master"):
            return self._derived_checker.check_pokemon_master()
        
        # Complete Pokedex
        if ach_id.endswith("_pokedex_complete"):
            config = get_game_config(self.game_name) if GAME_CONFIGS_AVAILABLE else None
            caught_count = self._derived_checker.get_caught_count()
            max_pokemon = config.max_pokemon if config else 150
            return caught_count >= max_pokemon
        
        return False
    
    def _check_derived_legacy(self, achievement: Achievement) -> bool:
        """Legacy hardcoded achievement checks for Gen 1 (fallback)"""
        if not self.game_name:
            return False
        
        game_key = self.game_name.lower().replace(" ", "_")
        ach_id = achievement.id.lower()
        
        # Pokedex achievements
        if "pokedex" in ach_id:
            return self._check_pokedex_achievement_legacy(achievement)
        
        # All gyms achievement
        if ach_id.endswith("_gym_all"):
            return self._check_all_gyms_legacy()
        
        # Elite Four achievements
        if "elite_four" in ach_id and not ach_id.endswith("_all"):
            return self._check_elite_four_member_legacy(achievement)
        
        # All Elite Four
        if ach_id.endswith("_elite_four_all"):
            return self._check_all_elite_four_legacy()
        
        # Legendary achievements
        if "legendary" in ach_id:
            if any(x in ach_id for x in ["moltres", "zapdos", "articuno", "mewtwo"]):
                return self._check_legendary_caught_legacy(achievement)
            elif ach_id.endswith("_legendary_birds"):
                return self._check_all_legendary_birds_legacy()
            elif ach_id.endswith("_legendary_all"):
                return self._check_all_legendaries_legacy()
        
        # First Steps
        if "first_steps" in ach_id:
            return self._check_first_steps_legacy()
        
        # Pokemon Master
        if ach_id.endswith("_pokemon_master"):
            return self._check_pokemon_master_legacy()
        
        return False
    
    def _check_pokedex_achievement_legacy(self, achievement: Achievement) -> bool:
        """Legacy pokedex count check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        caught_count = len(current_pokedex)
        
        ach_id = achievement.id
        if "_pokedex_10" in ach_id:
            return caught_count >= 10
        elif "_pokedex_25" in ach_id:
            return caught_count >= 25
        elif "_pokedex_50" in ach_id:
            return caught_count >= 50
        elif "_pokedex_100" in ach_id:
            return caught_count >= 100
        elif "_pokedex_150" in ach_id or "_pokedex_complete" in ach_id:
            return caught_count >= 150
        elif "_pokedex_151" in ach_id:
            return caught_count >= 151
        
        return False
    
    def _check_all_gyms_legacy(self) -> bool:
        """Legacy all gyms check"""
        badge_addr = "0xD356"
        if "gold" in self.game_name.lower() or "silver" in self.game_name.lower() or "crystal" in self.game_name.lower():
            badge_addr = "0xD35C"
        
        badge_byte = self.retroarch.read_memory(badge_addr)
        if badge_byte is not None:
            return badge_byte == 0xFF
        return False
    
    def _check_elite_four_member_legacy(self, achievement: Achievement) -> bool:
        """Legacy elite four member check"""
        ach_id = achievement.id.lower()
        e4_addresses = {"lorelei": "0xD6E0", "bruno": "0xD6E1", "agatha": "0xD6E2", "lance": "0xD6E3"}
        
        for name, addr in e4_addresses.items():
            if name in ach_id:
                value = self.retroarch.read_memory(addr)
                if value is not None and value > 0:
                    return True
        return False
    
    def _check_all_elite_four_legacy(self) -> bool:
        """Legacy all elite four check"""
        e4_addresses = ["0xD6E0", "0xD6E1", "0xD6E2", "0xD6E3"]
        defeated_count = 0
        
        for addr in e4_addresses:
            value = self.retroarch.read_memory(addr)
            if value is not None and value > 0:
                defeated_count += 1
        
        return defeated_count >= 4
    
    def _check_legendary_caught_legacy(self, achievement: Achievement) -> bool:
        """Legacy legendary caught check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        ach_id = achievement.id.lower()
        
        legendary_ids = {"mewtwo": 150, "moltres": 146, "zapdos": 145, "articuno": 144}
        
        for name, pokemon_id in legendary_ids.items():
            if name in ach_id:
                return pokemon_id in current_pokedex
        return False
    
    def _check_all_legendary_birds_legacy(self) -> bool:
        """Legacy all legendary birds check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        birds = [144, 145, 146]
        return all(bird in current_pokedex for bird in birds)
    
    def _check_all_legendaries_legacy(self) -> bool:
        """Legacy all legendaries check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        legendaries = [144, 145, 146, 150]
        return all(leg in current_pokedex for leg in legendaries)
    
    def _check_first_steps_legacy(self) -> bool:
        """Legacy first steps check"""
        if not self.pokemon_reader:
            return False
        
        party = self.pokemon_reader.read_party(self.game_name)
        starter_ids = {1, 4, 7}  # Bulbasaur, Charmander, Squirtle
        
        for member in party:
            if member.get("id") in starter_ids:
                return True
        return False
    
    def _check_pokemon_master_legacy(self) -> bool:
        """Legacy pokemon master check"""
        if not self.pokemon_reader:
            return False
        
        # Check all gyms
        if not self._check_all_gyms_legacy():
            return False
        
        # Check champion
        champion_addr = "0xD357"
        value = self.retroarch.read_memory(champion_addr)
        if not (value and value & 0x01):
            return False
        
        # Check complete pokedex
        current_pokedex = self.pokemon_reader.read_pokedex(self.game_name)
        return len(current_pokedex) >= 151
        
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
        
        # First read after game load/start establishes baseline only
        if not self._collection_baseline_initialized:
            self._last_pokedex = current_pokedex
            self._last_party = current_party
            self._collection_baseline_initialized = True
            return

        profile = self._get_validation_profile()

        # Detect suspicious empty reads after we already had a populated baseline.
        if not current_pokedex and len(self._last_pokedex) >= 10:
            self._handle_bad_read("empty_pokedex_after_non_empty")
            return

        # Find new catches
        new_catches = [p for p in current_pokedex if p not in self._last_pokedex]

        # Guard against bad memory reads causing impossible bulk catch spikes.
        if len(new_catches) > profile["max_new_catches_per_poll"]:
            log_event(
                logging.WARNING,
                "collection_spike_ignored",
                game=self.game_name,
                spike_count=len(new_catches),
                threshold=profile["max_new_catches_per_poll"],
            )
            self._handle_bad_read("bulk_catch_spike")
            self._last_pokedex = current_pokedex
            self._last_party = current_party
            return
        self._bad_read_streak = 0
        
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
            event_id = f"unlock:{self.game_id}:{achievement.id}"
            self._api_queue.put({"type": "achievement", "achievement": achievement, "event_id": event_id, "confidence": "high"})
    
    def post_collection_to_platform(self, catches: List[int], party: List[Dict], game: str):
        """Queue collection update for API posting"""
        if self.api:
            payload_key = json.dumps({"catches": sorted(catches), "party": party, "game": game}, sort_keys=True, default=str)
            event_id = "collection:" + sha256(payload_key.encode()).hexdigest()[:24]
            confidence = "high" if len(catches) <= 2 else "medium"
            self._api_queue.put({
                "type": "collection",
                "catches": catches,
                "party": party,
                "game": game,
                "event_id": event_id,
                "confidence": confidence,
            })
    
    def evaluate_condition(self, value: int, condition: str) -> bool:
        """Evaluate a memory condition"""
        condition = condition.strip()
        
        if condition.startswith(">="):
            try:
                return value >= int(condition[2:].strip())
            except ValueError:
                pass
        elif condition.startswith("<="):
            try:
                return value <= int(condition[2:].strip())
            except ValueError:
                pass
        elif condition.startswith(">"):
            try:
                return value > int(condition[1:].strip())
            except ValueError:
                pass
        elif condition.startswith("<"):
            try:
                return value < int(condition[1:].strip())
            except ValueError:
                pass
        elif condition.startswith("=="):
            try:
                return value == int(condition[2:].strip())
            except ValueError:
                pass
        elif condition.startswith("!="):
            try:
                return value != int(condition[2:].strip())
            except ValueError:
                pass
        elif condition.startswith("&"):
            try:
                target = int(condition[1:].strip(), 16) if "x" in condition else int(condition[1:].strip())
                return (value & target) == target
            except ValueError:
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
        self.root.title("🎮 PokeAchieve Tracker v1.9")
        self.root.geometry("980x700")
        self.root.minsize(760, 520)
        self._configure_styles()
        
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
        log_event(logging.DEBUG, "startup_paths", script_dir=str(self.script_dir))
        log_event(logging.DEBUG, "startup_paths", achievements_dir=str(self.achievements_dir))
        log_event(logging.DEBUG, "startup_paths", achievements_exists=self.achievements_dir.exists())
        
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
        self.retroarch = RetroArchClient(
            host=self.config.get("retroarch_host", "127.0.0.1"),
            port=int(self.config.get("retroarch_port", 55355))
        )
        self.api = None
        if self.config.get("api_key"):
            self.api = PokeAchieveAPI(
                base_url=self.config.get("api_url", "https://pokeachieve.com"),
                api_key=self.config["api_key"]
            )
        self.tracker = AchievementTracker(self.retroarch, self.api)
        
        # State
        self.is_running = False
        self.status_check_interval = 3000
        self.poll_interval = self.config.get("poll_interval", 2000)
        self.api_sync_enabled = self.config.get("api_sync", True)
        self._status_check_in_flight = False
        self._max_log_lines = 500
        self._max_recent_lines = 200
        self._max_catch_lines = 200
        self._api_worker_thread: Optional[threading.Thread] = None
        self._api_worker_stop = threading.Event()
        self._api_status_state = "Not configured"
        self._last_sync_status = "Idle"
        self.sent_events_file = self.data_dir / "sent_events.json"
        self._sent_event_ids = self._load_sent_events()

        self._build_ui()
        self._start_status_check()
        self.root.after(250, self._maybe_run_setup_wizard)
    
    def _configure_styles(self):
        """Apply a cleaner, modern ttk theme and spacing."""
        style = ttk.Style(self.root)
        for theme in ("clam", "vista", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        style.configure("TNotebook", tabposition="n")
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Subtle.TLabel", foreground="#4b5563")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 7))

    def _load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                log_event(logging.WARNING, "config_load_failed", file=str(self.config_file), error=str(exc))
        return {}
    
    def _save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except OSError as exc:
            log_event(logging.WARNING, "config_save_failed", file=str(self.config_file), error=str(exc))
    
    def _load_sent_events(self) -> set[str]:
        if not self.sent_events_file.exists():
            return set()
        try:
            with open(self.sent_events_file, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return set()

    def _save_sent_events(self):
        try:
            with open(self.sent_events_file, "w") as f:
                json.dump(sorted(self._sent_event_ids), f, indent=2)
        except OSError as exc:
            log_event(logging.WARNING, "sent_events_save_failed", error=str(exc))

    def _set_api_status(self, state: str):
        self._api_status_state = state
        self.api_status_label.configure(text=f"API: {state}")

    def _maybe_run_setup_wizard(self):
        if self.config.get("setup_completed"):
            return
        if not messagebox.askyesno("Setup Wizard", "Run quick setup now? (RetroArch + API)"):
            return

        host = simpledialog.askstring("RetroArch Host", "RetroArch host:", initialvalue=self.config.get("retroarch_host", "127.0.0.1"), parent=self.root)
        port = simpledialog.askinteger("RetroArch Port", "RetroArch UDP command port:", initialvalue=int(self.config.get("retroarch_port", 55355)), parent=self.root, minvalue=1, maxvalue=65535)
        if host and port:
            self.config["retroarch_host"] = host.strip()
            self.config["retroarch_port"] = int(port)
            self.retroarch.host = self.config["retroarch_host"]
            self.retroarch.port = self.config["retroarch_port"]

        key = simpledialog.askstring("API Key", "Paste API key (optional):", initialvalue=self.config.get("api_key", ""), parent=self.root)
        if key is not None:
            self.config["api_key"] = key.strip()
            if self.config["api_key"]:
                self.api = PokeAchieveAPI(self.config.get("api_url", "https://pokeachieve.com"), self.config["api_key"])
                self.tracker.api = self.api
                self._test_api_connection()

        self.config["setup_completed"] = True
        self._save_config()

    def _export_diagnostics(self):
        snapshot = {
            "generated_at": datetime.now().isoformat(),
            "retroarch": {"connected": self.retroarch.connected, "host": self.retroarch.host, "port": self.retroarch.port},
            "game": self.tracker.game_name,
            "api_status": self._api_status_state,
            "sync_status": self._last_sync_status,
            "queue": {
                "api_pending": self.tracker._api_queue.qsize(),
                "collection_pending": self.tracker._collection_queue.qsize(),
                "unlock_pending": self.tracker._unlock_queue.qsize(),
            },
            "validation_profile": self.tracker._get_validation_profile() if self.tracker.game_name else None,
        }
        default = self.data_dir / f"diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = filedialog.asksaveasfilename(title="Export Diagnostics", defaultextension=".json", initialfile=default.name, initialdir=str(self.data_dir), filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, "w") as f:
            json.dump(snapshot, f, indent=2)
        self._log(f"Diagnostics exported: {path}", "success")

    def _build_ui(self):
        """Build the user interface"""
        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        
        # Status Tab
        self.status_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.status_frame, text="Status")
        self._build_status_tab()
        
        # Achievements Tab
        self.achievements_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.achievements_frame, text="Achievements")
        self._build_achievements_tab()
        
        # Collection Tab (NEW!)
        self.collection_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.collection_frame, text="Collection")
        self._build_collection_tab()
        
        # Log Tab
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="Log")
        self._build_log_tab()
    
    def _build_status_tab(self):
        """Build status tab"""
        container = ttk.Frame(self.status_frame, padding=8)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Tracker Overview", style="Header.TLabel").pack(anchor=tk.W, padx=4, pady=(2, 8))
        ttk.Label(
            container,
            text="Connection, progress, and controls in one place.",
            style="Subtle.TLabel"
        ).pack(anchor=tk.W, padx=4, pady=(0, 12))

        # Connection status
        conn_frame = ttk.LabelFrame(container, text="Connection Status", padding=12)
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        self.ra_status_label = ttk.Label(conn_frame, text="RetroArch: Disconnected")
        self.ra_status_label.pack(anchor=tk.W, pady=1)

        self.api_status_label = ttk.Label(conn_frame, text="API: Not configured")
        self.api_status_label.pack(anchor=tk.W, pady=1)

        self.sync_status_label = ttk.Label(conn_frame, text="Sync: Idle")
        self.sync_status_label.pack(anchor=tk.W, pady=1)

        self.game_label = ttk.Label(conn_frame, text="Game: None")
        self.game_label.pack(anchor=tk.W, pady=1)

        # Progress
        progress_frame = ttk.LabelFrame(container, text="Progress", padding=12)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_label = ttk.Label(progress_frame, text="0/0 (0%) - 0/0 pts")
        self.progress_label.pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(8, 0))

        # Collection Summary
        collection_frame = ttk.LabelFrame(container, text="Pokemon Collection", padding=12)
        collection_frame.pack(fill=tk.X, pady=(0, 10))

        self.collection_label = ttk.Label(collection_frame, text="Caught: 0 | Shiny: 0 | Party: 0")
        self.collection_label.pack(anchor=tk.W)

        # Controls
        controls_frame = ttk.LabelFrame(container, text="Actions", padding=10)
        controls_frame.pack(fill=tk.X)
        for col in range(6):
            controls_frame.columnconfigure(col, weight=1)

        self.start_btn = ttk.Button(
            controls_frame,
            text="▶ Start Tracking",
            command=self._start_tracking,
            style="Primary.TButton"
        )
        self.start_btn.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self.stop_btn = ttk.Button(
            controls_frame,
            text="⏹ Stop",
            command=self._stop_tracking,
            state='disabled'
        )
        self.stop_btn.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        ttk.Button(controls_frame, text="🔄 Sync", command=self._sync_with_server).grid(
            row=0, column=2, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="⚙ Settings", command=self._show_settings).grid(
            row=0, column=3, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="🗑 Clear Data", command=self._clear_app_data).grid(
            row=0, column=4, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="📦 Export Diagnostics", command=self._export_diagnostics).grid(
            row=0, column=5, padx=4, pady=4, sticky="ew"
        )

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
    
    def _trim_scrolled_text(self, widget: scrolledtext.ScrolledText, max_lines: int):
        """Keep text widgets fast by trimming old lines."""
        line_count = int(widget.index('end-1c').split('.')[0])
        if line_count > max_lines:
            widget.delete('1.0', f"{line_count - max_lines + 1}.0")

    def _log(self, message: str, level: str = "info"):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "ℹ", "success": "✅", "error": "❌", "unlock": "🏆", "api": "🌐", "collection": "📱"}.get(level, "ℹ")
        
        self.log_text.configure(state='normal')
        self.log_text.insert('end', f"[{timestamp}] {prefix} {message}\n")
        self._trim_scrolled_text(self.log_text, self._max_log_lines)
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
    
    def _start_status_check(self):
        """Start periodic status check"""
        self._check_status()

    def _run_status_probe(self) -> Dict:
        """Run network status checks outside the Tk main thread."""
        ra_connected = self.retroarch.connected
        if not ra_connected:
            ra_connected = self.retroarch.connect()

        game_name = self.retroarch.get_current_game() if ra_connected else None
        return {
            "ra_connected": ra_connected,
            "game_name": game_name,
            "api_configured": bool(self.api),
        }

    def _check_status(self):
        """Check RetroArch connection and game status without freezing the UI."""
        if self._status_check_in_flight:
            self.root.after(self.status_check_interval, self._check_status)
            return

        self._status_check_in_flight = True

        def worker():
            status = self._run_status_probe()
            self.root.after(0, lambda: self._apply_status_probe(status))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_status_probe(self, status: Dict):
        """Apply async status results on the Tk main thread."""
        try:
            if status.get("ra_connected"):
                self.ra_status_label.configure(text="RetroArch: Connected ✓")
                self._detect_game(status.get("game_name"))
            else:
                self.ra_status_label.configure(text="RetroArch: Disconnected")

            if status.get("api_configured"):
                if self._api_status_state == "Not configured":
                    self._set_api_status("Configured")
            else:
                self._set_api_status("Not configured")
            self.sync_status_label.configure(text=f"Sync: {self._last_sync_status}")
        finally:
            self._status_check_in_flight = False
            self.root.after(self.status_check_interval, self._check_status)
    
    def _detect_game(self, detected_game_name: Optional[str] = None):
        """Detect which game is loaded"""
        game_name = detected_game_name or self.retroarch.get_current_game()
        
        if game_name:
            # If game changed, load new achievements
            if game_name != self.tracker.game_name:
                self._log(f"Game detected: {game_name}")
                self._load_game_achievements(game_name)
            # If same game but not running, restart tracking
            elif not self.is_running and self.tracker.achievements:
                self._log(f"Resuming tracking for {game_name}")
                self._start_tracking()
    
    def _load_game_achievements(self, game_name: str):
        """Load achievements for detected game"""
        # Strip ROM hack suffixes like "(Enhanced)" for matching
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        log_event(logging.INFO, "load_achievements_start", game=game_name)
        log_event(logging.DEBUG, "load_achievements_clean_name", clean_name=clean_name)
        log_event(logging.DEBUG, "load_achievements_dir", path=str(self.achievements_dir))
        log_event(logging.DEBUG, "load_achievements_dir_exists", exists=self.achievements_dir.exists())
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
        clean_lower = clean_name.lower()
        log_event(logging.DEBUG, "load_achievements_clean_lower", clean_lower=clean_lower)
        for key, filename in game_map.items():
            key_lower = key.lower()
            log_event(logging.DEBUG, "load_achievements_match_check", key=key_lower, candidate=clean_lower)
            # Check if key is in cleaned name (handles "pokemon emerald" in "pokemon - emerald version playing")
            if key_lower in clean_lower:
                achievement_file = self.achievements_dir / filename
                display_name = key
                log_event(logging.INFO, "load_achievements_match", game=key, file=filename)
                break
            # Also try matching individual words (e.g., "emerald" matches)
            key_words = key_lower.replace("pokemon ", "")
            if key_words in clean_lower:
                achievement_file = self.achievements_dir / filename
                display_name = key
                log_event(logging.INFO, "load_achievements_word_match", game=key, file=filename)
                break
        
        log_event(logging.DEBUG, "load_achievements_match_scan", candidate=clean_name.lower())
        for key, filename in game_map.items():
            log_event(logging.DEBUG, "load_achievements_scan_item", key=key.lower(), candidate=clean_name.lower())
        log_event(logging.DEBUG, "load_achievements_file", file=str(achievement_file) if achievement_file else None)
        log_event(logging.DEBUG, "load_achievements_file_exists", exists=achievement_file.exists() if achievement_file else False)
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
            
            success, unlocked_ids = self.api.get_progress(game_id)
            if success:
                server_unlocked = set(unlocked_ids or [])

                # Update local achievements to include server ones
                newly_added = 0
                for ach in self.tracker.achievements:
                    by_id = ach.id in server_unlocked
                    by_name = f"name:{ach.name.strip().lower()}" in server_unlocked
                    if (by_id or by_name) and not ach.unlocked:
                        ach.unlocked = True
                        ach.unlocked_at = datetime.now()
                        newly_added += 1

                if newly_added > 0:
                    self._log(f"Synced {newly_added} achievements from website", "info")
                    self.tracker.save_progress(self.progress_file)
        except Exception as e:
            self._log(f"Could not sync with website: {e}", "warning")
    
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
        self._start_api_worker()
        self._log("Tracking started - Monitoring achievements and Pokemon collection", "success")
        
        # Start processing queues
        self._check_unlocks()
        self._process_collection_updates()
    
    def _stop_tracking(self):
        """Stop tracking"""
        self.is_running = False
        self._stop_api_worker()
        self.tracker.stop_polling()
        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self._log("Tracking stopped")
        self.tracker.save_progress(self.progress_file)
        # Clear game name so it can be re-detected and restarted
        self.tracker.game_name = None
    
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
    
    def _threadsafe_log(self, message: str, level: str = "info"):
        """Schedule log writes from worker threads safely onto Tk main loop."""
        self.root.after(0, lambda: self._log(message, level))

    def _start_api_worker(self):
        """Start a single API worker to process queued sync jobs sequentially."""
        if not hasattr(self, "_api_worker_thread"):
            self._api_worker_thread = None
        if not hasattr(self, "_api_worker_stop"):
            self._api_worker_stop = threading.Event()

        if not (self.api and self.config.get("api_sync", True)):
            self._last_sync_status = "Disabled"
            self.root.after(0, lambda: self.sync_status_label.configure(text=f"Sync: {self._last_sync_status}"))
            return

        if self._api_worker_thread and self._api_worker_thread.is_alive():
            return

        self._api_worker_stop.clear()

        def worker():
            while not self._api_worker_stop.is_set():
                try:
                    item = self.tracker._api_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                self._last_sync_status = "Syncing"
                self.root.after(0, lambda: self.sync_status_label.configure(text=f"Sync: {self._last_sync_status}"))
                success = self._process_api_item(item)
                if not success and not self._api_worker_stop.is_set():
                    retries = item.get("retries", 0)
                    if retries < 3:
                        item["retries"] = retries + 1
                        backoff_seconds = 2 ** retries
                        time.sleep(backoff_seconds)
                        self.tracker._api_queue.put(item)

                self.tracker._api_queue.task_done()
                self._last_sync_status = "Idle"
                self.root.after(0, lambda: self.sync_status_label.configure(text=f"Sync: {self._last_sync_status}"))

        self._api_worker_thread = threading.Thread(target=worker, daemon=True)
        self._api_worker_thread.start()

    def _stop_api_worker(self):
        """Signal API worker to stop; leaves queued items for next start."""
        if not hasattr(self, "_api_worker_stop"):
            self._api_worker_stop = threading.Event()
        self._api_worker_stop.set()

    def _process_api_item(self, item: Dict) -> bool:
        """Post one queued API update. Returns True when delivered."""
        if not self.api:
            return True

        event_id = item.get("event_id")
        if event_id and event_id in self._sent_event_ids:
            log_event(logging.INFO, "api_event_deduped", event_id=event_id)
            return True

        item_type = item.get("type")
        if item_type == "achievement":
            ach = item.get("achievement")
            if not ach or not self.tracker.game_id:
                return True
            success, data = self.api.post_unlock(self.tracker.game_id, ach.id)
            if success:
                if event_id:
                    self._sent_event_ids.add(event_id)
                    self._save_sent_events()
                self._threadsafe_log(f"Posted unlock to platform: {ach.name}", "api")
                return True
            self._threadsafe_log(f"Failed to post unlock: {data.get('error', 'Unknown error')}", "error")
            return False

        if item_type == "collection":
            catches = item.get("catches", [])
            party = item.get("party", [])
            game = item.get("game", "")
            success = self._sync_collection_to_api(catches, party, game)
            if success and event_id:
                self._sent_event_ids.add(event_id)
                self._save_sent_events()
            return success

        return True
    
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
    
    def _sync_collection_to_api(self, catches: List[int], party: List[Dict], game: str) -> bool:
        """Sync collection data to PokeAchieve API"""
        log_event(logging.INFO, "collection_sync_start", catches=len(catches), party=len(party), game=game)
        
        if not catches and not party:
            print("[COLLECTION SYNC] Nothing to sync")
            return True
        
        # Build batch update for new catches
        batch = []
        for pokemon_id in catches:
            entry = {
                "pokemon_id": pokemon_id,
                "pokemon_name": self._get_pokemon_name(pokemon_id),
                "caught": True,
                "shiny": False,
                "game": game,
                "game_id": self.tracker.GAME_IDS.get(game, 0)
            }
            batch.append(entry)
            log_event(logging.DEBUG, "collection_sync_batch_item", entry=entry)
        
        if batch:
            log_event(logging.INFO, "collection_sync_batch_send", count=len(batch))
            success, data = self.api.post_collection_batch(batch)
            if success:
                self._threadsafe_log(f"Synced {len(batch)} Pokemon to collection", "api")
                print(f"[COLLECTION SYNC] Success: {data}")
            else:
                error_msg = data.get('error', 'Unknown error')
                self._threadsafe_log(f"Failed to sync collection: {error_msg}", "error")
                print(f"[COLLECTION SYNC] Failed: {error_msg}")
                return False
        
        # Update party
        for member in party:
            log_event(logging.DEBUG, "collection_sync_party_update", slot=member.get("slot"), pokemon_id=member["id"])
            success, data = self.api.post_party_update(
                member["id"],
                True,
                member.get("slot")
            )
            if success:
                self._threadsafe_log(f"Updated party: {member['id']} in slot {member.get('slot')}", "api")
            else:
                error_msg = data.get('error', 'Unknown error')
                self._threadsafe_log(f"Failed to update party: {error_msg}", "error")
                return False
    
        return True

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
        self._trim_scrolled_text(self.catches_list, self._max_catch_lines)
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
        self._trim_scrolled_text(self.recent_list, self._max_recent_lines)
        self.recent_list.configure(state='disabled')
        
        self.tracker.save_progress(self.progress_file)
        
        try:
            self.root.bell()
        except tk.TclError:
            pass
    
    def _update_progress(self):
        """Update progress display"""
        progress = self.tracker.get_progress()
        self.progress_label.configure(
            text=f"{progress['unlocked']}/{progress['total']} ({progress['percentage']:.1f}%) - {progress['points']}/{progress['total_points']} pts"
        )
        self.progress_bar['value'] = progress['percentage']
    

    def _clear_app_data(self):
        """Clear all local app data (progress and config)"""
        import tkinter.messagebox as msgbox
        
        confirm = msgbox.askyesno(
            "Clear App Data",
            "This will delete all local progress and settings. Are you sure? This cannot be undone!",
            icon='warning'
        )
        
        if confirm:
            try:
                if self.is_running:
                    self._stop_tracking()

                # Clear progress file
                if self.progress_file.exists():
                    self.progress_file.unlink()
                
                # Clear config file
                if self.config_file.exists():
                    self.config_file.unlink()
                
                # Clear tracker state
                self.tracker.achievements = []
                self.tracker.game_name = None
                self.tracker.game_id = None
                self.tracker._last_party = []
                self.tracker._last_pokedex = []
                self.tracker._collection_baseline_initialized = False
                self.tracker._unlock_streaks = {}
                self._sent_event_ids = set()
                self._save_sent_events()
                self._set_api_status("Not configured" if not self.api else "Configured")

                self.game_label.configure(text="Game: None")
                self.progress_label.configure(text="0/0 (0%) - 0/0 pts")
                self.progress_bar["value"] = 0
                self.collection_label.configure(text="Caught: 0 | Shiny: 0 | Party: 0")
                self.party_display.configure(text="No party data yet - start tracking to see your Pokemon!")

                self._threadsafe_log("Local app data cleared", "info")
                msgbox.showinfo("Success", "App data cleared! Restart the tracker to start fresh.")
                
            except Exception as e:
                msgbox.showerror("Error", f"Failed to clear data: {e}")
    
    def _sync_with_server(self):
        """Sync achievements with PokeAchieve.com server"""
        import tkinter.messagebox as msgbox

        if not self.api:
            msgbox.showwarning("Not Connected", 
                "No API key configured. Go to Settings → API to add your API key.")
            return

        if not self.tracker.game_id:
            msgbox.showwarning("No Game", "Load a supported Pokemon game before syncing progress.")
            return

        try:
            newly_synced, errors = self.tracker.sync_with_platform()
            if errors:
                msgbox.showerror("Sync Failed", "Could not fetch progress from server.")
                return

            self.tracker.save_progress(self.progress_file)
            self._update_progress()
            self._threadsafe_log(f"Synced {newly_synced} achievements from server", "api")
            msgbox.showinfo("Sync Complete", f"Synced {newly_synced} achievements from server!")
        except Exception as e:
            msgbox.showerror("Sync Error", f"Failed to sync: {e}")
    
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

        retro_frame = ttk.LabelFrame(dialog, text="RetroArch", padding="10")
        retro_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        retro_frame.columnconfigure(1, weight=1)
        ttk.Label(retro_frame, text="Host:").grid(row=0, column=0, sticky="w", pady=5)
        host_entry = ttk.Entry(retro_frame)
        host_entry.insert(0, self.config.get("retroarch_host", "127.0.0.1"))
        host_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        ttk.Label(retro_frame, text="Port:").grid(row=1, column=0, sticky="w", pady=5)
        port_entry = ttk.Entry(retro_frame)
        port_entry.insert(0, str(self.config.get("retroarch_port", 55355)))
        port_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        ttk.Label(api_frame, text="Platform URL:").grid(row=0, column=0, sticky="w", pady=5)
        url_entry = ttk.Entry(api_frame)
        url_entry.insert(0, self.config.get("api_url", "https://pokeachieve.com"))
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
            self.config["retroarch_host"] = host_entry.get().strip() or "127.0.0.1"
            try:
                self.config["retroarch_port"] = int(port_entry.get())
            except ValueError:
                self.config["retroarch_port"] = 55355
            self.retroarch.host = self.config["retroarch_host"]
            self.retroarch.port = int(self.config["retroarch_port"])
            
            if self.config["api_key"]:
                self.api = PokeAchieveAPI(self.config["api_url"], self.config["api_key"])
                self.tracker.api = self.api
                if self.is_running:
                    self._start_api_worker()
            else:
                self.api = None
                self.tracker.api = None
                self._stop_api_worker()

            self._save_config()
            self._log("Settings saved")
            dialog.destroy()
            self._test_api_connection()
        
        ttk.Button(dialog, text="Save", command=save).grid(row=5, column=0, pady=10)
        
        dialog.columnconfigure(0, weight=1)
    
    def _test_api_connection(self):
        """Test API connection"""
        if self.api:
            def test():
                success, message = self.api.test_auth()
                if success:
                    self._set_api_status("Authenticated")
                    self._log("API authentication successful", "success")
                else:
                    self._set_api_status("Configured (auth failed)")
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
