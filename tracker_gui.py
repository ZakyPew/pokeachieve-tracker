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
from collections import Counter, deque
import urllib.request
import urllib.error
from urllib.parse import urlparse, urlunparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Tuple, Set
from datetime import datetime
from hashlib import sha256
from dataclasses import dataclass, asdict

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False

LOGGER = logging.getLogger("pokeachieve_tracker")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)


def _format_log_fields(fields: Dict[str, object]) -> str:
    parts: List[str] = []
    for key in sorted(fields.keys()):
        value = fields.get(key)
        rendered = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)


def log_event(log_level: int, event: str, **fields):
    """Structured logging helper."""
    if fields:
        LOGGER.log(log_level, "%s | %s", event, _format_log_fields(fields))
    else:
        LOGGER.log(log_level, "%s", event)



def _format_party_slot_line(member: Dict[str, object], *, debug_style: bool, name_resolver: Optional[Callable[[int], str]] = None) -> Optional[str]:
    """Render a party slot line for debug/tracker logs with optional metadata."""
    if not isinstance(member, dict):
        return None

    try:
        slot = int(member.get("slot", 0))
    except (TypeError, ValueError):
        return None
    if slot <= 0:
        return None

    pokemon_id = 0
    try:
        pokemon_id = int(member.get("id", 0))
    except (TypeError, ValueError):
        pokemon_id = 0

    name = member.get("name")
    if not isinstance(name, str) or not name.strip():
        if callable(name_resolver) and pokemon_id > 0:
            try:
                name = name_resolver(pokemon_id)
            except Exception:
                name = None
    if not isinstance(name, str) or not name.strip():
        name = f"Pokemon #{pokemon_id}" if pokemon_id > 0 else "Unknown"

    level_int = None
    level_value = member.get("level")
    try:
        level_candidate = int(level_value) if level_value is not None else None
        if level_candidate is not None and level_candidate > 0:
            level_int = level_candidate
    except (TypeError, ValueError):
        level_int = None

    if debug_style:
        base = f"Party Slot {slot}: {name}"
        if level_int is not None:
            base = f"Party Slot {slot}: {name}, Lv.{level_int}"
    else:
        base = f"SLOT {slot}: {name}"
        if level_int is not None:
            base = f"SLOT {slot}: Lv.{level_int} {name}"

    details: List[str] = []
    details.append("Shiny" if bool(member.get("shiny")) else "Normal")
    for label, key in (("Gender", "gender"), ("Nature", "nature"), ("Ability", "ability")):
        value = member.get(key)
        if isinstance(value, str) and value.strip():
            details.append(f"{label}: {value.strip()}")

    moves = member.get("moves")
    if isinstance(moves, list):
        for move in moves:
            if isinstance(move, str) and move.strip():
                details.append(move.strip())

    if details:
        base = f"{base} / {' / '.join(details)}"
    return base

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
    target_value: Optional[int] = None
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

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        """Normalize platform URL and strip accidental trailing /api path."""
        raw = (base_url or "https://pokeachieve.com").strip()
        if not raw:
            raw = "https://pokeachieve.com"
        if "://" not in raw:
            raw = f"https://{raw}"

        parsed = urlparse(raw)
        path = (parsed.path or "").rstrip("/")
        lower_path = path.lower()
        # Treat pasted API endpoint paths as base-domain input.
        if lower_path == "/api" or lower_path.startswith("/api/"):
            path = ""

        return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", "")).rstrip("/")
    
    def __init__(self, base_url: str = "https://pokeachieve.com", api_key: str = ""):
        self.base_url = self.normalize_base_url(base_url)
        self.api_key = api_key.strip() if api_key else ""
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "PokeAchieveTracker/1.0"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
        self._tracker_user_achievements_forbidden = False
        self._public_games_catalog_unsupported = False
        self._achievement_catalog_cache: Dict[int, List[dict]] = {}

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
                try:
                    return True, json.loads(body)
                except json.JSONDecodeError as exc:
                    if endpoint.startswith("/games/") and endpoint.endswith("/achievements"):
                        self._public_games_catalog_unsupported = True
                    log_event(logging.ERROR, "api_exception", method=method, endpoint=endpoint, error_type=type(exc).__name__, error=str(exc))
                    return False, {"error": str(exc), "status": status}
        except urllib.error.HTTPError as e:
            status = e.getcode()
            error_body = e.read().decode()
            if endpoint == "/api/users/me/achievements" and status in {401, 403}:
                self._tracker_user_achievements_forbidden = True
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
        unlocked: List[str] = []

        def add_item(item: dict):
            if not isinstance(item, dict):
                return
            if item.get("game_id") not in (None, game_id):
                return

            nested = item.get("achievement") if isinstance(item.get("achievement"), dict) else {}
            ach_id = (
                item.get("id")
                or item.get("achievement_id")
                or nested.get("id")
            )
            ach_name = (
                nested.get("name")
                or item.get("achievement_name")
                or item.get("name")
            )

            if ach_id is not None:
                unlocked.append(str(ach_id))
            if isinstance(ach_name, str) and ach_name.strip():
                unlocked.append(f"name:{ach_name.strip().lower()}")

        if isinstance(data, dict):
            if isinstance(data.get("unlocked_achievement_ids"), list):
                unlocked.extend(str(x) for x in data.get("unlocked_achievement_ids", []))

            achievements = data.get("achievements")
            if isinstance(achievements, list):
                for item in achievements:
                    if not isinstance(item, dict):
                        continue
                    marked_unlocked = bool(
                        item.get("unlocked")
                        or item.get("is_unlocked")
                        or item.get("status") == "unlocked"
                    )
                    if marked_unlocked:
                        add_item(item)

        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("unlocked") or item.get("is_unlocked") or item.get("status") == "unlocked":
                    add_item(item)

        if not unlocked:
            return []

        # Preserve order while removing duplicates.
        return list(dict.fromkeys(unlocked))

    def _get_achievement_catalog(self, game_id: int, force_refresh: bool = False) -> List[dict]:
        """Load and cache game achievement catalog from tracker API."""
        if not force_refresh and game_id in self._achievement_catalog_cache:
            return self._achievement_catalog_cache.get(game_id, [])

        success, data = self._request("GET", f"/api/games/{game_id}/achievements")
        if success and isinstance(data, list):
            self._achievement_catalog_cache[game_id] = data
            return data
        return []

    def _augment_unlocked_with_catalog_names(self, game_id: int, unlocked: List[str]) -> List[str]:
        """Add name:... tokens by mapping unlocked IDs through game catalog."""
        if not unlocked:
            return []

        numeric_ids: Set[str] = set()
        for token in unlocked:
            if token is None:
                continue
            text = str(token).strip()
            if text.isdigit():
                numeric_ids.add(text)

        if not numeric_ids:
            return list(dict.fromkeys(str(token) for token in unlocked if token is not None))

        catalog = self._get_achievement_catalog(game_id)
        if not catalog:
            return list(dict.fromkeys(str(token) for token in unlocked if token is not None))

        augmented: List[str] = [str(token) for token in unlocked if token is not None]
        for item in catalog:
            if not isinstance(item, dict):
                continue
            ach_id = item.get("id") or item.get("achievement_id")
            name = item.get("name") or item.get("achievement_name")
            if ach_id is None or not isinstance(name, str) or not name.strip():
                continue
            if str(ach_id) in numeric_ids:
                augmented.append(f"name:{name.strip().lower()}")

        return list(dict.fromkeys(augmented))

    def _resolve_achievement_id(self, game_id: int, achievement_name: Optional[str], achievement_string_id: Optional[str] = None) -> Optional[str]:
        """Resolve an achievement identifier string accepted by /api/tracker/unlock."""
        target_name = achievement_name.strip().lower() if isinstance(achievement_name, str) and achievement_name.strip() else None
        target_string_id = str(achievement_string_id).strip().lower() if achievement_string_id else None

        catalog = self._get_achievement_catalog(game_id)
        for item in catalog:
            if not isinstance(item, dict):
                continue
            string_id = str(item.get("string_id") or item.get("achievement_string_id") or "").strip()
            name = str(item.get("name") or item.get("achievement_name") or "").strip().lower()
            ach_id = item.get("id") or item.get("achievement_id")
            if target_string_id and string_id and target_string_id == string_id.lower():
                if ach_id is not None:
                    return str(ach_id)
                return string_id
            if target_name and name and target_name == name:
                if ach_id is not None:
                    return str(ach_id)
                if string_id:
                    return string_id

        # Fallback: some deployments still expose user-achievement listing to API keys.
        if target_name and (not self.api_key) and not self._tracker_user_achievements_forbidden:
            success, data = self._request("GET", "/api/users/me/achievements")
            if success and isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if item.get("game_id") not in (None, game_id):
                        continue
                    nested = item.get("achievement") if isinstance(item.get("achievement"), dict) else {}
                    ach_name = nested.get("name") or item.get("achievement_name")
                    ach_id = nested.get("id") or item.get("achievement_id") or item.get("id")
                    if isinstance(ach_name, str) and ach_name.strip().lower() == target_name and ach_id is not None:
                        return str(ach_id)
        return None

    def test_auth(self) -> tuple[bool, str]:
        """Test tracker API-key authentication using tracker test endpoint."""
        success, data = self._request("POST", "/api/tracker/test")
        if success:
            username = data.get("username") if isinstance(data, dict) else None
            message = data.get("message") if isinstance(data, dict) else None
            if username:
                return True, f"{message or 'API key valid'} ({username})"
            return True, message or "API key valid"
        return False, data.get("error", "Authentication failed")
    
    def get_progress(self, game_id: int) -> tuple[bool, list]:
        """Get user's progress for a game."""
        success, data = self._request("GET", f"/api/tracker/progress/{game_id}")
        if success:
            unlocked = self._extract_unlocked_ids(data, game_id)
            unlocked = self._augment_unlocked_with_catalog_names(game_id, unlocked)

            # This endpoint is not available to tracker API keys on many deployments.
            # Only call it when no explicit API key is configured.
            if (not self.api_key) and (not self._tracker_user_achievements_forbidden):
                more_success, more_data = self._request("GET", "/api/users/me/achievements")
                if more_success:
                    unlocked.extend(self._extract_unlocked_ids(more_data, game_id))
                    unlocked = list(dict.fromkeys(unlocked))
            return True, unlocked

        # Backwards compatibility with legacy backend route
        legacy_success, legacy_data = self._request("GET", "/users/me/achievements")
        if legacy_success:
            return True, self._extract_unlocked_ids(legacy_data, game_id)

        return False, []
    
    def post_unlock(self, game_id: int, achievement_id: str, achievement_name: Optional[str] = None) -> tuple[bool, dict]:
        """Post achievement unlock to platform."""
        resolved_initial = None
        if achievement_name:
            resolved_initial = self._resolve_achievement_id(game_id, achievement_name, achievement_id)

        catalog_known = bool(self._achievement_catalog_cache.get(game_id))
        if achievement_name and resolved_initial is None and catalog_known:
            return True, {
                "skipped": True,
                "reason": "achievement_not_mapped",
                "status": 404,
                "error": "Achievement not mapped to platform catalog",
            }

        primary_id = str(resolved_initial) if resolved_initial is not None else str(achievement_id)
        attempted_ids = set()

        def _post_with_id(candidate_id: str) -> tuple[bool, dict]:
            payload = {
                "game_id": game_id,
                "achievement_id": str(candidate_id),
                "unlocked_at": datetime.now().isoformat(),
            }
            return self._request("POST", "/api/tracker/unlock", payload)

        success, data = _post_with_id(primary_id)
        attempted_ids.add(str(primary_id))
        if success:
            return True, data

        status = data.get("status") if isinstance(data, dict) else None
        error_text = str(data.get("error", "")).lower() if isinstance(data, dict) else ""

        # Some API deployments require different achievement identifiers.
        if status in {400, 404, 422} and achievement_name:
            resolved_id = self._resolve_achievement_id(game_id, achievement_name, achievement_id)
            if resolved_id is not None and str(resolved_id) not in attempted_ids:
                resolved_success, resolved_data = _post_with_id(str(resolved_id))
                attempted_ids.add(str(resolved_id))
                if resolved_success:
                    return True, resolved_data
                data = resolved_data
                status = data.get("status") if isinstance(data, dict) else status
                error_text = str(data.get("error", "")).lower() if isinstance(data, dict) else error_text

            if str(achievement_id) not in attempted_ids:
                original_success, original_data = _post_with_id(str(achievement_id))
                attempted_ids.add(str(achievement_id))
                if original_success:
                    return True, original_data
                data = original_data
                status = data.get("status") if isinstance(data, dict) else status
                error_text = str(data.get("error", "")).lower() if isinstance(data, dict) else error_text

        # The local tracker may include custom achievements not present on the platform.
        if status == 404 and "achievement not found" in error_text:
            return True, {
                "skipped": True,
                "reason": "achievement_not_found",
                "status": status,
                "error": "Achievement not found on platform",
            }

        # Only try legacy routes when the tracker endpoint itself is unavailable.
        if status != 404:
            return False, data

        legacy_payload = {
            "game_id": game_id,
            "achievement_id": str(achievement_id),
            "achievement_name": achievement_name,
            "unlocked_at": datetime.now().isoformat()
        }
        return self._request("POST", "/progress/update", legacy_payload)
    
    # Pokemon Collection API Methods
    def post_collection_batch(self, pokemon_list: List[Dict]) -> tuple[bool, dict]:
        """Post batch of Pokemon collection updates"""
        success, data = self._request("POST", "/api/collection/batch-update", pokemon_list)
        if not success:
            # Backwards compatibility with legacy backend route
            return self._request("POST", "/collection/batch-update", pokemon_list)
        return success, data

    def start_session(self, game_id: int) -> tuple[bool, dict]:
        success, data = self._request("POST", "/sessions/start", {"game_id": game_id})
        if success:
            return True, data
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
        self.command_timeout_seconds = 1.0
        self._command_timeout_count = 0
        self._socket_reset_counts: Dict[str, int] = {}
        self._io_error_streak = 0
        self._last_io_error_ts = 0.0
        self._waiting_for_launch = False
        self._waiting_since_ts = 0.0
    
    def connect(self) -> bool:
        """Connect to RetroArch"""
        try:
            with self.lock:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Keep a short timeout so transient packet loss does not stall polling for seconds.
                self.socket.settimeout(self.command_timeout_seconds)
                # UDP does not need connect.
                self.connected = True
                self._command_timeout_count = 0
                self._socket_reset_counts = {}
                self._io_error_streak = 0
                self._last_io_error_ts = 0.0
            return True
        except Exception:
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from RetroArch"""
        with self.lock:
            self.connected = False
            self._waiting_for_launch = False
            self._waiting_since_ts = 0.0
            if self.socket:
                try:
                    self.socket.close()
                except OSError:
                    pass
                self.socket = None

    def is_waiting_for_launch(self) -> bool:
        """True while RetroArch appears closed/unreachable and tracker is waiting for launch."""
        return bool(self._waiting_for_launch)

    def _enter_waiting_for_launch(self, command: str, reason: str, error: Optional[str] = None):
        """Enter compact offline mode and emit one concise wait message."""
        if self._waiting_for_launch:
            return
        self._waiting_for_launch = True
        self._waiting_since_ts = time.time()
        log_event(
            logging.INFO,
            "retroarch_closed_waiting",
            status="RetroArch Closed, waiting on RetroArch launch",
        )

    def _exit_waiting_for_launch(self, command: str):
        """Exit offline mode after first successful response."""
        if not self._waiting_for_launch:
            return
        downtime_ms = 0
        if self._waiting_since_ts > 0:
            downtime_ms = int(max(0.0, time.time() - self._waiting_since_ts) * 1000)
        self._waiting_for_launch = False
        self._waiting_since_ts = 0.0
        log_event(
            logging.INFO,
            "retroarch_reconnected",
            status="RetroArch detected, resuming polling",
            command=command,
            downtime_ms=downtime_ms,
        )

    def _drain_stale_packets(self, max_packets: int = 8) -> int:
        """Drain stale UDP packets so delayed responses do not pollute new commands."""
        if not self.socket or max_packets <= 0:
            return 0

        drained = 0
        previous_timeout = self.socket.gettimeout()
        try:
            self.socket.settimeout(0.0)
            while drained < int(max_packets):
                try:
                    self.socket.recvfrom(4096)
                    drained += 1
                except (BlockingIOError, socket.timeout):
                    break
                except OSError:
                    break
        finally:
            try:
                self.socket.settimeout(previous_timeout)
            except OSError:
                pass
        return drained

    def send_command(self, command: str) -> Optional[str]:
        """Send a command to RetroArch and get response."""
        with self.lock:
            if not self.connected or not self.socket:
                return None
            # While RetroArch is offline, only probe with GET_STATUS.
            if self._waiting_for_launch and command != "GET_STATUS":
                return None

            try:
                dropped = self._drain_stale_packets(max_packets=8)
                if dropped:
                    log_event(
                        logging.DEBUG,
                        "retroarch_stale_packets_dropped",
                        command=command,
                        dropped=int(dropped),
                    )

                # UDP uses sendto and recvfrom.
                self.socket.sendto(f"{command}\n".encode(), (self.host, self.port))
                command_parts = command.split()
                expected_prefix = command_parts[0] if command_parts else command
                expected_read_addr: Optional[int] = None
                expected_read_len: Optional[int] = None
                if expected_prefix == "READ_CORE_MEMORY" and len(command_parts) >= 3:
                    try:
                        expected_read_addr = int(str(command_parts[1]), 16)
                    except (TypeError, ValueError):
                        expected_read_addr = None
                    try:
                        expected_read_len = int(str(command_parts[2]), 0)
                    except (TypeError, ValueError):
                        expected_read_len = None

                def _response_matches(candidate_text: str) -> bool:
                    if not candidate_text.startswith(expected_prefix):
                        return False

                    if expected_prefix != "READ_CORE_MEMORY":
                        return True

                    if expected_read_addr is None:
                        return True

                    parts = candidate_text.split()
                    if len(parts) < 3:
                        return False

                    try:
                        response_addr = int(str(parts[1]), 16)
                    except (TypeError, ValueError):
                        return False

                    if int(response_addr) != int(expected_read_addr):
                        return False

                    if expected_read_len is not None and (len(parts) - 2) < int(expected_read_len):
                        return False

                    return True

                response_text: Optional[str] = None
                mismatched = 0
                self.socket.settimeout(self.command_timeout_seconds)

                response, _addr = self.socket.recvfrom(4096)
                candidate = response.decode(errors="replace").strip()
                if _response_matches(candidate):
                    response_text = candidate
                else:
                    mismatched = 1
                    short_timeout = max(0.01, min(0.05, float(self.command_timeout_seconds) / 20.0))
                    max_recovery_reads = 10 if expected_prefix == "READ_CORE_MEMORY" else 5
                    self.socket.settimeout(short_timeout)
                    for _ in range(max_recovery_reads):
                        try:
                            response, _addr = self.socket.recvfrom(4096)
                        except socket.timeout:
                            break
                        candidate = response.decode(errors="replace").strip()
                        if _response_matches(candidate):
                            response_text = candidate
                            break
                        mismatched += 1
                self.socket.settimeout(self.command_timeout_seconds)
                if response_text is None:
                    self._command_timeout_count += 1
                    self._io_error_streak += 1
                    self._last_io_error_ts = time.time()
                    log_event(
                        logging.WARNING,
                        "retroarch_response_mismatch",
                        command=command,
                        expected=expected_prefix,
                        mismatched=mismatched,
                        expected_addr=hex(expected_read_addr) if expected_read_addr is not None else None,
                    )
                    return None
                if mismatched:
                    log_event(
                        logging.INFO,
                        "retroarch_response_recovered",
                        command=command,
                        expected=expected_prefix,
                        dropped=mismatched,
                        expected_addr=hex(expected_read_addr) if expected_read_addr is not None else None,
                    )
                self._exit_waiting_for_launch(command=command)
                self._command_timeout_count = 0
                self._socket_reset_counts[command] = 0
                self._io_error_streak = 0
                self._last_io_error_ts = 0.0
                return response_text
            except ConnectionResetError as exc:
                # On Windows UDP sockets, transient ICMP port-unreachable can surface as WSAECONNRESET.
                # Treat repeated resets as RetroArch being offline and suppress noisy per-read warnings.
                self._io_error_streak += 1
                self._last_io_error_ts = time.time()
                count = int(self._socket_reset_counts.get(command, 0)) + 1
                self._socket_reset_counts[command] = count
                self._enter_waiting_for_launch(command=command, reason="socket_reset", error=str(exc))
                return None
            except socket.timeout:
                # Timeouts are expected occasionally on UDP; keep session alive.
                self._command_timeout_count += 1
                self._io_error_streak += 1
                self._last_io_error_ts = time.time()
                if command == "GET_STATUS":
                    self._enter_waiting_for_launch(command=command, reason="timeout")
                return None
            except OSError as exc:
                self._io_error_streak += 1
                self._last_io_error_ts = time.time()
                self.connected = False
                log_event(
                    logging.ERROR,
                    "retroarch_socket_error",
                    command=command,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return None
            except Exception as exc:
                self._io_error_streak += 1
                self._last_io_error_ts = time.time()
                self.connected = False
                log_event(
                    logging.ERROR,
                    "retroarch_command_error",
                    command=command,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return None

    def is_unstable_io(self, max_age_seconds: float = 8.0, threshold: int = 3) -> bool:
        """Return True when recent RetroArch command transport is unstable."""
        if int(self._io_error_streak) < int(threshold):
            return False
        if float(self._last_io_error_ts) <= 0:
            return False
        return (time.time() - float(self._last_io_error_ts)) <= float(max_age_seconds)
    def _normalize_game_name(self, raw_text: str) -> Optional[str]:
        normalized = re.sub(r"[^a-z0-9]+", " ", raw_text.lower()).strip()
        for alias, canonical in self.GAME_ALIASES.items():
            if alias in normalized:
                return canonical
        return None

    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        if response:
            normalized = self._normalize_game_name(response)
            if normalized:
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
                        return normalized
                    return game_name
            except Exception as e:
                log_event(logging.WARNING, "game_parse_error", error=str(e))
                pass
        return None
    
    def read_memory(self, address: str, num_bytes: int = 1) -> Optional[int]:
        """Read memory from the emulator."""

        def _parse_response(response: Optional[str]) -> Optional[List[int]]:
            if response and response.startswith("READ_CORE_MEMORY"):
                parts = response.split()
                if len(parts) >= 3:
                    try:
                        return [int(x, 16) for x in parts[2:]]
                    except ValueError:
                        return None
            return None

        def _read_chunk_with_retry(read_addr: str, read_len: int) -> Optional[List[int]]:
            attempts = 2
            for _ in range(attempts):
                parsed = _parse_response(self.send_command(f"READ_CORE_MEMORY {read_addr} {read_len}"))
                if isinstance(parsed, list) and len(parsed) >= int(read_len):
                    return parsed
            return None

        try:
            total_bytes = int(num_bytes)
        except (TypeError, ValueError):
            total_bytes = 1
        if total_bytes <= 0:
            return None

        # Avoid oversized UDP payloads/responses on Windows (WinError 10040).
        max_chunk_bytes = 1200
        if total_bytes > max_chunk_bytes:
            try:
                base_addr = int(str(address), 16)
            except (TypeError, ValueError):
                parsed = _read_chunk_with_retry(str(address), int(total_bytes))
                if parsed is None:
                    return None
                return parsed[0] if len(parsed) == 1 else parsed

            values: List[int] = []
            offset = 0
            remaining = int(total_bytes)
            while remaining > 0:
                chunk = min(max_chunk_bytes, remaining)
                chunk_addr = hex(base_addr + offset)
                parsed = _read_chunk_with_retry(chunk_addr, int(chunk))
                if not parsed:
                    return None
                values.extend(parsed[:chunk])
                remaining -= chunk
                offset += chunk
            return values

        parsed = _read_chunk_with_retry(str(address), int(total_bytes))
        if parsed is None:
            return None
        return parsed[0] if len(parsed) == 1 else parsed

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
            "pokedex_caught": "0xD30A",    # Pokemon you've actually caught
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
            "layout_id": "gen3_ruby",
            # Ruby uses static SaveBlock layouts (no Emerald-style saveblock pointers).
            "pokedex_seen": "0x02024F00",
            "pokedex_caught": "0x02024ECC",
            "party_count": "0x02025968",
            "party_start": "0x0202596C",
            "enemy_party_start": "0x02025BC4",
            "party_slot_size": 100,
            "party_count_offset": 0x234,
            "party_start_offset": 0x238,
            "pokedex_caught_offset": 0x28,
            "pokedex_seen_offset": 0x5C,
            "party_count_candidates": ["0x02025968", "0x02024284", "0x020244E9"],
            "party_start_candidates": ["0x0202596C", "0x02024288", "0x020244EC"],
            "party_stride_candidates": [100, 200],
            "party_use_pointer_layout": 0,
            "party_max_pairs": 8,
            "party_enable_offset_scan": 0,
            "party_allow_double_stride": 0,
            "party_skip_scan_on_invalid_count": 1,
            "party_skip_scan_on_zero_count": 1,
            "party_allow_static_when_pointer_missing": 1,
            "pokedex_allow_static_when_pointer_missing": 1,
            "pokedex_allow_static_fallback": 0,
            "pokedex_allow_byte_fallback": 0,
        },
        "pokemon_sapphire": {
            "gen": 3,
            "max_pokemon": 386,
            "layout_id": "gen3_sapphire",
            # Sapphire uses static SaveBlock layouts (no Emerald-style saveblock pointers).
            "pokedex_seen": "0x02024F00",
            "pokedex_caught": "0x02024ECC",
            "party_count": "0x02025968",
            "party_start": "0x0202596C",
            "enemy_party_start": "0x02025BC4",
            "party_slot_size": 100,
            "party_count_offset": 0x234,
            "party_start_offset": 0x238,
            "pokedex_caught_offset": 0x28,
            "pokedex_seen_offset": 0x5C,
            "party_count_candidates": ["0x02025968", "0x02024284", "0x020244E9"],
            "party_start_candidates": ["0x0202596C", "0x02024288", "0x020244EC"],
            "party_stride_candidates": [100, 200],
            "party_use_pointer_layout": 0,
            "party_max_pairs": 8,
            "party_enable_offset_scan": 0,
            "party_allow_double_stride": 0,
            "party_skip_scan_on_invalid_count": 1,
            "party_skip_scan_on_zero_count": 1,
            "party_allow_static_when_pointer_missing": 1,
            "pokedex_allow_static_when_pointer_missing": 1,
            "pokedex_allow_static_fallback": 0,
            "pokedex_allow_byte_fallback": 0,
        },
        "pokemon_emerald": {
            "gen": 3,
            "max_pokemon": 386,
            "layout_id": "gen3_emerald",
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            # Emerald uses a different live party block than Ruby/Sapphire.
            "party_count": "0x020244E9",
            "party_start": "0x020244EC",
            "enemy_party_start": "0x02024744",
            "party_slot_size": 100,
            "party_force_byte_reads": 0,
            "party_allow_byte_fallback": 0,
            "party_ignore_count": 0,
            "party_max_pairs": 8,
            "party_enable_offset_scan": 0,
            "party_allow_double_stride": 0,
            "party_try_double_bulk": 1,
            "party_decode_budget_ms": 1800,
            # Keep alternate candidates for core/ROM variants.
            "party_count_candidates": ["0x020244E9", "0x02024284"],
            "party_start_candidates": ["0x020244EC", "0x02024550"],
            "party_stride_candidates": [100, 200],
            "pokedex_allow_byte_fallback": 0,
            # Emerald-specific saveblock pointers + offsets.
            "saveblock1_ptr": "0x03005D8C",
            "saveblock2_ptr": "0x03005D90",
            "party_count_offset": 0x234,
            "party_start_offset": 0x238,
            "pokedex_caught_offset": 0x28,
            "pokedex_seen_offset": 0x5C,
            "saveblock1_flags_offset": 0x1270,
            "adventure_started_flag": 0x74,
            "gym_progression_flags": [0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC],
            "party_use_pointer_layout": 0,
        },
        "pokemon_firered": {
            "gen": 3,
            "max_pokemon": 386,
            "layout_id": "gen3_firered",
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024288",
            "enemy_party_start": "0x020244E0",
            "party_slot_size": 100,
            "saveblock1_ptr": "0x03005008",
            "saveblock2_ptr": "0x0300500C",
            "party_count_offset": 0x234,
            "party_start_offset": 0x238,
            "pokedex_caught_offset": 0x28,
            "pokedex_seen_offset": 0x5C,
            "party_use_pointer_layout": 1,
            "party_skip_scan_on_invalid_count": 1,
            "party_allow_static_when_pointer_missing": 0,
            "pokedex_allow_static_when_pointer_missing": 0,
            "pokedex_allow_static_fallback": 0,
            "pokedex_allow_byte_fallback": 0,
        },
        "pokemon_leafgreen": {
            "gen": 3,
            "max_pokemon": 386,
            "layout_id": "gen3_leafgreen",
            "pokedex_seen": "0x02024C0C",
            "pokedex_caught": "0x02024D0C",
            "party_count": "0x02024284",
            "party_start": "0x02024288",
            "enemy_party_start": "0x020244E0",
            "party_slot_size": 100,
            "saveblock1_ptr": "0x03005008",
            "saveblock2_ptr": "0x0300500C",
            "party_count_offset": 0x234,
            "party_start_offset": 0x238,
            "pokedex_caught_offset": 0x28,
            "pokedex_seen_offset": 0x5C,
            "party_use_pointer_layout": 1,
            "party_skip_scan_on_invalid_count": 1,
            "party_allow_static_when_pointer_missing": 0,
            "pokedex_allow_static_when_pointer_missing": 0,
            "pokedex_allow_static_fallback": 0,
            "pokedex_allow_byte_fallback": 0,
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
        29: "Nidoran-F", 30: "Nidorina", 31: "Nidoqueen",
        32: "Nidoran-M", 33: "Nidorino", 34: "Nidoking",
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

    # Gen 3 encrypted party substructure orders by personality % 24.
    # Canonical Gen 3 substructure order by personality % 24.
    GEN3_PARTY_SUBSTRUCT_ORDERS = [
        (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 2, 3, 1), (0, 3, 1, 2), (0, 3, 2, 1),
        (1, 0, 2, 3), (1, 0, 3, 2), (1, 2, 0, 3), (1, 2, 3, 0), (1, 3, 0, 2), (1, 3, 2, 0),
        (2, 0, 1, 3), (2, 0, 3, 1), (2, 1, 0, 3), (2, 1, 3, 0), (2, 3, 0, 1), (2, 3, 1, 0),
        (3, 0, 1, 2), (3, 0, 2, 1), (3, 1, 0, 2), (3, 1, 2, 0), (3, 2, 0, 1), (3, 2, 1, 0),
    ]
    # Alternate sequence previously used by the tracker.
    GEN3_PARTY_SUBSTRUCT_ORDERS_ALT = [
        (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2), (0, 2, 3, 1), (0, 3, 2, 1),
        (1, 0, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
        (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2), (2, 3, 0, 1), (3, 2, 0, 1),
        (1, 2, 3, 0), (1, 3, 2, 0), (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
    ]
    GEN3_INTERNAL_SPECIES_MAX = 411
    GEN3_INTERNAL_UNOWN_START = 252
    GEN3_INTERNAL_UNOWN_END = 276
    GEN3_INTERNAL_NATIONAL_OFFSET_START = 277
    GEN3_INTERNAL_TO_NATIONAL_OFFSET = 25
    GEN3_UNOWN_NATIONAL_ID = 201
    GEN3_NATURE_NAMES = [
        "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
        "Bold", "Docile", "Relaxed", "Impish", "Lax",
        "Timid", "Hasty", "Serious", "Jolly", "Naive",
        "Modest", "Mild", "Quiet", "Bashful", "Rash",
        "Calm", "Gentle", "Sassy", "Careful", "Quirky",
    ]

    def __init__(self, retroarch: RetroArchClient):
        self.retroarch = retroarch
        self._saveblock_ptr_backoff_until: Dict[str, float] = {}
        self._saveblock_ptr_fail_count: Dict[str, int] = {}
        self._pointer_unreadable_last_log: Dict[str, float] = {}
        self._pointer_fallback_last_log: Dict[str, float] = {}
        self._pokedex_seen_less_last_log: Dict[str, float] = {}
        self._pointer_unreadable_streak: Dict[str, int] = {}
        self._pointer_unreadable_last_attempt: Dict[str, float] = {}
        self._last_gen3_party_selection: Dict[str, Dict[str, object]] = {}
        self._last_party_read_meta: Dict[str, object] = {}
        self._last_wild_read_meta: Dict[str, object] = {}
        self._gen3_gender_rates: Dict[int, int] = {}
        self._gen3_species_ability_ids: Dict[int, Tuple[int, int]] = {}
        self._gen3_ability_names: Dict[int, str] = {}
        self._gen3_move_names: Dict[int, str] = {}
        self._gen3_internal_to_national: Dict[int, int] = {}
        self._load_gen3_reference_data()

    @staticmethod
    def _humanize_identifier(identifier: str) -> str:
        """Convert canonical identifier names (kebab/snake) into display names."""
        if not isinstance(identifier, str):
            return ""
        cleaned = identifier.strip().replace("_", "-")
        if not cleaned:
            return ""
        words: List[str] = []
        for token in cleaned.split("-"):
            token = token.strip()
            if not token:
                continue
            words.append(token[0].upper() + token[1:])
        return " ".join(words)

    def _load_gen3_reference_data(self):
        """Load Gen 3 metadata lookup tables for party detail decoding."""
        base_dir = Path(__file__).resolve().parent
        gender_path = base_dir / "gen3_gender_map.json"
        species_ability_path = base_dir / "gen3_species_abilities.json"
        ability_name_path = base_dir / "gen3_ability_names.json"
        move_name_path = base_dir / "gen3_move_names.json"
        internal_species_path = base_dir / "gen3_internal_to_national.json"

        def _read_json(path: Path) -> Dict[str, object]:
            if not path.exists():
                return {}
            try:
                raw = path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception as exc:
                log_event(
                    logging.WARNING,
                    "gen3_reference_data_load_failed",
                    path=str(path),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return {}

        raw_gender = _read_json(gender_path)
        raw_species_abilities = _read_json(species_ability_path)
        raw_ability_names = _read_json(ability_name_path)
        raw_move_names = _read_json(move_name_path)
        raw_internal_species = _read_json(internal_species_path)

        gender_rates: Dict[int, int] = {}
        for key, value in raw_gender.items():
            try:
                gender_rates[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
        self._gen3_gender_rates = gender_rates

        species_ability_ids: Dict[int, Tuple[int, int]] = {}
        for key, value in raw_species_abilities.items():
            try:
                species_id = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, list):
                continue
            first = 0
            second = 0
            if len(value) >= 1:
                try:
                    first = int(value[0])
                except (TypeError, ValueError):
                    first = 0
            if len(value) >= 2:
                try:
                    second = int(value[1])
                except (TypeError, ValueError):
                    second = 0
            species_ability_ids[species_id] = (first, second)
        self._gen3_species_ability_ids = species_ability_ids

        ability_names: Dict[int, str] = {}
        for key, value in raw_ability_names.items():
            try:
                ability_id = int(key)
            except (TypeError, ValueError):
                continue
            rendered = self._humanize_identifier(str(value))
            if rendered:
                ability_names[ability_id] = rendered
        self._gen3_ability_names = ability_names

        move_names: Dict[int, str] = {}
        for key, value in raw_move_names.items():
            try:
                move_id = int(key)
            except (TypeError, ValueError):
                continue
            rendered = self._humanize_identifier(str(value))
            if rendered:
                move_names[move_id] = rendered
        self._gen3_move_names = move_names

        internal_to_national: Dict[int, int] = {}
        for key, value in raw_internal_species.items():
            try:
                internal_species = int(key)
                national_species = int(value)
            except (TypeError, ValueError):
                continue
            if internal_species > 0 and national_species > 0:
                internal_to_national[internal_species] = national_species
        self._gen3_internal_to_national = internal_to_national

        if not (
            self._gen3_gender_rates
            and self._gen3_species_ability_ids
            and self._gen3_ability_names
            and self._gen3_move_names
            and self._gen3_internal_to_national
        ):
            log_event(
                logging.WARNING,
                "gen3_reference_data_incomplete",
                genders=len(self._gen3_gender_rates),
                species_abilities=len(self._gen3_species_ability_ids),
                abilities=len(self._gen3_ability_names),
                moves=len(self._gen3_move_names),
                internal_species_map=len(self._gen3_internal_to_national),
            )
        else:
            log_event(
                logging.INFO,
                "gen3_reference_data_loaded",
                genders=len(self._gen3_gender_rates),
                species_abilities=len(self._gen3_species_ability_ids),
                abilities=len(self._gen3_ability_names),
                moves=len(self._gen3_move_names),
                internal_species_map=len(self._gen3_internal_to_national),
            )

    # Gen 1 (RBY) uses internal species ordering in party data.
    # Source: pret/pokered data/pokemon/dex_order.asm
    GEN1_INTERNAL_TO_NATIONAL = {
        1: 112, 2: 115, 3: 32, 4: 35, 5: 21, 6: 100, 7: 34, 8: 80, 9: 2, 10: 103,
        11: 108, 12: 102, 13: 88, 14: 94, 15: 29, 16: 31, 17: 104, 18: 111, 19: 131,
        20: 59, 21: 151, 22: 130, 23: 90, 24: 72, 25: 92, 26: 123, 27: 120, 28: 9,
        29: 127, 30: 114, 33: 58, 34: 95, 35: 22, 36: 16, 37: 79, 38: 64, 39: 75,
        40: 113, 41: 67, 42: 122, 43: 106, 44: 107, 45: 24, 46: 47, 47: 54, 48: 96,
        49: 76, 51: 126, 53: 125, 54: 82, 55: 109, 57: 56, 58: 86, 59: 50, 60: 128,
        64: 83, 65: 48, 66: 149, 70: 84, 71: 60, 72: 124, 73: 146, 74: 144, 75: 145,
        76: 132, 77: 52, 78: 98, 82: 37, 83: 38, 84: 25, 85: 26, 88: 147, 89: 148,
        90: 140, 91: 141, 92: 116, 93: 117, 96: 27, 97: 28, 98: 138, 99: 139,
        100: 39, 101: 40, 102: 133, 103: 136, 104: 135, 105: 134, 106: 66, 107: 41,
        108: 23, 109: 46, 110: 61, 111: 62, 112: 13, 113: 14, 114: 15, 116: 85,
        117: 57, 118: 51, 119: 49, 120: 87, 123: 10, 124: 11, 125: 12, 126: 68,
        128: 55, 129: 97, 130: 42, 131: 150, 132: 143, 133: 129, 136: 89, 138: 99,
        139: 91, 141: 101, 142: 36, 143: 110, 144: 53, 145: 105, 147: 93, 148: 63,
        149: 65, 150: 17, 151: 18, 152: 121, 153: 1, 154: 3, 155: 73, 157: 118,
        158: 119, 163: 77, 164: 78, 165: 19, 166: 20, 167: 33, 168: 30, 169: 74,
        170: 137, 171: 142, 173: 81, 176: 4, 177: 7, 178: 5, 179: 8, 180: 6,
        185: 43, 186: 44, 187: 45, 188: 69, 189: 70, 190: 71,
    }

    def get_pokemon_name(self, pokemon_id: int) -> str:
        """Get Pokemon name from ID"""
        return self.POKEMON_NAMES.get(pokemon_id, f"Pokemon #{pokemon_id}")

    def _resolve_gen1_species_id(self, raw_species_id: int) -> int:
        """Convert Gen 1 internal species IDs to National Dex IDs when possible."""
        try:
            species_int = int(raw_species_id) & 0xFF
        except (TypeError, ValueError):
            return 0
        mapped = self.GEN1_INTERNAL_TO_NATIONAL.get(species_int)
        return int(mapped) if isinstance(mapped, int) and mapped > 0 else int(species_int)

    def get_last_party_read_meta(self) -> Dict[str, object]:
        """Return metadata from the most recent party read attempt."""
        return dict(self._last_party_read_meta)

    def get_last_wild_read_meta(self) -> Dict[str, object]:
        """Return metadata from the most recent wild encounter read attempt."""
        return dict(self._last_wild_read_meta)

    def _normalize_gen3_species_id(self, species_id: int) -> Optional[int]:
        """Map Gen 3 internal species IDs to National Dex IDs."""
        try:
            normalized = int(species_id)
        except (TypeError, ValueError):
            return None

        if normalized <= 0 or normalized > int(self.GEN3_INTERNAL_SPECIES_MAX):
            return None

        mapped_species = self._gen3_internal_to_national.get(normalized)
        if mapped_species is not None:
            try:
                mapped_species_id = int(mapped_species)
            except (TypeError, ValueError):
                return None
            max_national_species = max(self.POKEMON_NAMES.keys()) if self.POKEMON_NAMES else 0
            if mapped_species_id > 0 and mapped_species_id <= int(max_national_species):
                return int(mapped_species_id)
            return None

        # Fallback mapping for environments where the lookup table is unavailable.
        if int(self.GEN3_INTERNAL_UNOWN_START) <= normalized <= int(self.GEN3_INTERNAL_UNOWN_END):
            return int(self.GEN3_UNOWN_NATIONAL_ID)

        if normalized >= int(self.GEN3_INTERNAL_NATIONAL_OFFSET_START):
            normalized -= int(self.GEN3_INTERNAL_TO_NATIONAL_OFFSET)

        return normalized

    def get_game_config(self, game_name: str) -> Optional[Dict]:
        """Get memory addresses for current game - uses game_configs when available"""
        # Strip ROM hack suffixes like "(Enhanced)", "(U)", etc.
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        game_key = clean_name.lower().replace(" ", "_").replace("'", "").strip()
        
        # Legacy table may carry game-specific runtime layout metadata.
        legacy = self.GAME_ADDRESSES.get(game_key) or {}

        # Try new game_configs system first, then overlay game-specific legacy extras.
        if GAME_CONFIGS_AVAILABLE:
            config = get_game_config(clean_name)
            if config:
                resolved = {
                    "gen": config.generation,
                    "max_pokemon": config.max_pokemon,
                    "pokedex_caught": config.pokedex_caught_start,
                    "pokedex_seen": config.pokedex_seen_start,
                    "party_count": config.party_count_address,
                    "party_start": config.party_start_address,
                    "party_slot_size": config.party_slot_size,
                    "badge_address": config.badge_address,
                    "champion_address": config.champion_address,
                    "hall_of_fame_address": config.hall_of_fame_address,
                }
                # Legacy table contains game-specific hotfixes; allow it to override.
                resolved.update(legacy)
                return resolved

        # Fallback to legacy hardcoded addresses.
        return legacy if legacy else None
    
    def validate_memory_profile(self, game_name: str) -> Dict[str, object]:
        """Validate key memory addresses for the selected game."""
        config = self.get_game_config(game_name)
        if not config:
            return {"ok": False, "reason": "missing_config"}

        checks = {
            "pokedex_caught": config.get("pokedex_caught"),
            "party_count": config.get("party_count"),
            "badge_address": config.get("badge_address"),
        }
        if int(config.get("gen", 1)) == 3:
            hall_of_fame_addr = config.get("hall_of_fame_address")
            champion_addr = config.get("champion_address")
            if hall_of_fame_addr:
                checks["hall_of_fame_address"] = hall_of_fame_addr
            if champion_addr:
                checks["champion_address"] = champion_addr

        failures = []
        for key, addr in checks.items():
            if not addr:
                failures.append(f"{key}:missing")
                continue
            value = self.retroarch.read_memory(addr)
            if value is None:
                failures.append(f"{key}:unreadable")

        # Gen 3 pointer checks are advisory; some cores hide IWRAM pointer globals.
        warnings: List[str] = []
        if int(config.get("gen", 1)) == 3:
            for ptr_key in ("saveblock1_ptr", "saveblock2_ptr"):
                ptr_addr = config.get(ptr_key)
                if not ptr_addr:
                    continue
                checks[ptr_key] = ptr_addr
                if self._resolve_gen3_saveblock_ptr(ptr_addr, game_name=game_name) is None:
                    warnings.append(f"{ptr_key}:unreadable")

        return {"ok": len(failures) == 0, "failures": failures, "warnings": warnings, "checks": checks}

    def _read_u32_le(self, address: str) -> Optional[int]:
        """Read a 32-bit little-endian value from memory."""
        values = self.retroarch.read_memory(address, 4)
        if isinstance(values, list) and len(values) >= 4:
            return int(values[0]) | (int(values[1]) << 8) | (int(values[2]) << 16) | (int(values[3]) << 24)

        # Fallback to single-byte reads for cores that only return one byte per command.
        bytes_out: List[int] = []
        try:
            base = int(address, 16)
        except (TypeError, ValueError):
            return None

        for offset in range(4):
            val = self.retroarch.read_memory(hex(base + offset))
            if not isinstance(val, int):
                return None
            bytes_out.append(val)

        return int(bytes_out[0]) | (int(bytes_out[1]) << 8) | (int(bytes_out[2]) << 16) | (int(bytes_out[3]) << 24)
    def _resolve_gen3_saveblock_ptr(self, pointer_addr: str, game_name: Optional[str] = None) -> Optional[int]:
        """Resolve a Gen 3 save block pointer and validate EWRAM range."""
        key = f"{(game_name or '').lower()}:{str(pointer_addr).lower()}"
        now = time.time()
        if float(self._saveblock_ptr_backoff_until.get(key, 0.0)) > now:
            return None

        ptr = self._read_u32_le(pointer_addr)
        if ptr is None:
            failures = int(self._saveblock_ptr_fail_count.get(key, 0)) + 1
            self._saveblock_ptr_fail_count[key] = failures
            self._saveblock_ptr_backoff_until[key] = now + min(20.0, 1.5 * failures)
            return None

        # Gen 3 working RAM range (EWRAM); reject null/garbage pointers.
        if 0x02000000 <= int(ptr) < 0x02040000:
            self._saveblock_ptr_fail_count[key] = 0
            self._saveblock_ptr_backoff_until[key] = 0.0
            self._pointer_unreadable_streak[key] = 0
            self._pointer_unreadable_last_attempt[key] = 0.0
            return int(ptr)

        failures = int(self._saveblock_ptr_fail_count.get(key, 0)) + 1
        self._saveblock_ptr_fail_count[key] = failures
        self._saveblock_ptr_backoff_until[key] = now + min(20.0, 1.5 * failures)
        return None
    def _resolve_gen3_saveblock1_base(self, config: Dict, game_name: Optional[str] = None) -> Optional[int]:
        """Resolve SaveBlock1 base from pointer or static fallback math."""
        ptr_addr = config.get("saveblock1_ptr")
        if ptr_addr:
            ptr = self._resolve_gen3_saveblock_ptr(ptr_addr, game_name=game_name)
            if ptr is not None:
                return ptr

        party_count_addr = config.get("party_count")
        party_count_offset = config.get("party_count_offset")
        if party_count_addr and party_count_offset is not None:
            try:
                return int(party_count_addr, 16) - int(party_count_offset)
            except (TypeError, ValueError):
                return None
        return None

    def read_gen3_event_flag(self, game_name: str, flag_id: int) -> Optional[bool]:
        """Read a Gen 3 event flag from SaveBlock1 flags array."""
        config = self.get_game_config(game_name)
        if not config or int(config.get("gen", 1)) != 3:
            return None

        flags_offset = config.get("saveblock1_flags_offset")
        if flags_offset is None:
            return None

        base = self._resolve_gen3_saveblock1_base(config, game_name=game_name)
        if base is None:
            return None

        try:
            flag = int(flag_id)
        except (TypeError, ValueError):
            return None

        byte_addr = hex(base + int(flags_offset) + (flag // 8))
        byte_val = self.retroarch.read_memory(byte_addr)
        if not isinstance(byte_val, int):
            return None

        return bool((int(byte_val) >> (flag & 7)) & 1)

    def _log_pointer_unreadable_throttled(self, game_name: str, pointer: str, layout: Optional[str] = None):
        """Throttle noisy pointer-unreadable logs during transient UDP instability."""
        if bool(getattr(self.retroarch, "is_waiting_for_launch", lambda: False)()):
            return

        key = f"{game_name}:{pointer}"
        now = time.time()

        # Treat bursts within a single poll as one failure signal.
        last_attempt = float(self._pointer_unreadable_last_attempt.get(key, 0.0))
        streak = int(self._pointer_unreadable_streak.get(key, 0))
        if now - last_attempt >= 0.75:
            streak += 1
            self._pointer_unreadable_streak[key] = streak
            self._pointer_unreadable_last_attempt[key] = now

        # Suppress startup noise; only warn when failures persist across multiple polls.
        if streak < 3:
            return

        last = float(self._pointer_unreadable_last_log.get(key, 0.0))
        if now - last < 20.0:
            return
        self._pointer_unreadable_last_log[key] = now
        log_event(
            logging.WARNING,
            "gen3_saveblock_pointer_unreadable",
            game=game_name,
            pointer=pointer,
            layout=layout,
            streak=streak,
        )

    def _log_pointer_fallback_skipped_throttled(self, game_name: str, kind: str, pointer_addr: str, static_addr: str):
        """Throttle noisy pointer-fallback-skipped info logs while pointers jitter."""
        if bool(getattr(self.retroarch, "is_waiting_for_launch", lambda: False)()):
            return

        if not hasattr(self, "_pointer_fallback_last_log"):
            self._pointer_fallback_last_log = {}

        key = f"{game_name}:{kind}:fallback_skipped"
        now = time.time()
        last = float(self._pointer_fallback_last_log.get(key, 0.0))
        if now - last < 15.0:
            return
        self._pointer_fallback_last_log[key] = now
        log_event(
            logging.INFO,
            "gen3_pointer_fallback_skipped",
            game=game_name,
            kind=kind,
            pointer_addr=pointer_addr,
            static_addr=static_addr,
        )
    def _resolve_gen3_gender_label(self, species_id: int, personality: int) -> str:
        """Resolve displayed gender from species gender rate and PID."""
        try:
            gender_rate = int(self._gen3_gender_rates.get(int(species_id)))
        except (TypeError, ValueError):
            return "Unknown"

        if gender_rate < 0:
            return "Genderless"
        if gender_rate <= 0:
            return "Male"
        if gender_rate >= 8:
            return "Female"

        threshold = int(gender_rate) * 32
        pid_low = int(personality) & 0xFF
        return "Female" if pid_low < threshold else "Male"

    def _resolve_gen3_ability_name(self, species_id: int, ability_slot: int) -> Optional[str]:
        """Resolve ability display name for a species using Gen 3 ability slot bit."""
        ability_pair = self._gen3_species_ability_ids.get(int(species_id))
        if not ability_pair:
            return None

        first_id = int(ability_pair[0]) if len(ability_pair) > 0 else 0
        second_id = int(ability_pair[1]) if len(ability_pair) > 1 else 0

        selected_id = second_id if int(ability_slot) == 1 and second_id > 0 else first_id
        if selected_id <= 0:
            return None

        return self._gen3_ability_names.get(int(selected_id), f"Ability #{int(selected_id)}")

    def _resolve_gen3_move_name(self, move_id: int) -> str:
        """Resolve move display name for Gen 3 move IDs."""
        try:
            mid = int(move_id)
        except (TypeError, ValueError):
            return "Unknown Move"
        if mid <= 0:
            return "Unknown Move"
        return self._gen3_move_names.get(mid, f"Move #{mid}")

    def _resolve_legacy_move_name(self, move_id: int) -> str:
        """Resolve Gen 1/2 move labels when canonical tables are unavailable."""
        try:
            mid = int(move_id)
        except (TypeError, ValueError):
            return "-"
        if mid <= 0:
            return "-"
        return f"Move #{mid}"

    def _is_gen3_shiny(self, personality: int, ot_id: int) -> bool:
        """Determine Gen 3 shininess from PID and OTID."""
        shiny_value = self._gen3_shiny_value(personality, ot_id)
        if shiny_value is None:
            return False
        return int(shiny_value) < 8

    def _gen3_shiny_value(self, personality: int, ot_id: int) -> Optional[int]:
        """Return Gen 3 shiny XOR value from PID and OTID."""
        try:
            pid = int(personality) & 0xFFFFFFFF
            oid = int(ot_id) & 0xFFFFFFFF
        except (TypeError, ValueError):
            return None

        return int(((oid >> 16) ^ (oid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF)

    def _is_gen2_shiny_from_dvs(self, atk_def_byte: int, spd_spc_byte: int) -> bool:
        """Determine Gen 2 shininess from DV bytes."""
        try:
            ad = int(atk_def_byte) & 0xFF
            ss = int(spd_spc_byte) & 0xFF
        except (TypeError, ValueError):
            return False

        atk_dv = (ad >> 4) & 0xF
        def_dv = ad & 0xF
        spd_dv = (ss >> 4) & 0xF
        spc_dv = ss & 0xF

        return def_dv == 10 and spd_dv == 10 and spc_dv == 10 and atk_dv in {2, 3, 6, 7, 10, 11, 14, 15}

    def _decode_gen3_party_slot_details(self, slot_bytes: List[int], max_species_id: int, allow_checksum_mismatch: bool = False, species_hint_ids: Optional[Set[int]] = None) -> Optional[Dict[str, object]]:
        """Decode species + metadata from encrypted Gen 3 party slot data."""
        if not isinstance(slot_bytes, list) or len(slot_bytes) < 100:
            return None

        max_national_species = max(self.POKEMON_NAMES.keys())
        hint_species_ids: Set[int] = set()
        if isinstance(species_hint_ids, (set, list, tuple)):
            for raw_id in species_hint_ids:
                try:
                    normalized_hint = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if normalized_hint > 0:
                    hint_species_ids.add(normalized_hint)
        try:
            max_known_move_id = max(int(mid) for mid in self._gen3_move_names.keys())
        except Exception:
            max_known_move_id = 0
        if int(max_known_move_id) <= 0:
            max_known_move_id = 354

        def _decode_once(candidate_bytes: List[int], allow_checksum_mismatch_local: bool = False) -> Optional[Dict[str, object]]:
            if len(candidate_bytes) < 100:
                return None

            def read_u16(buffer: List[int], offset: int) -> int:
                return int(buffer[offset]) | (int(buffer[offset + 1]) << 8)

            def read_u32(buffer: List[int], offset: int) -> int:
                return (
                    int(buffer[offset])
                    | (int(buffer[offset + 1]) << 8)
                    | (int(buffer[offset + 2]) << 16)
                    | (int(buffer[offset + 3]) << 24)
                )

            personality = read_u32(candidate_bytes, 0)
            ot_id = read_u32(candidate_bytes, 4)
            if personality == 0 and ot_id == 0:
                return None

            # Header bytes are not encrypted; they help disambiguate byte-order variants
            # that can still decrypt into plausible secure substructures.
            language_id = int(candidate_bytes[18]) & 0xFF if len(candidate_bytes) > 18 else -1
            markings = int(candidate_bytes[27]) & 0xFF if len(candidate_bytes) > 27 else 0
            misc_flags = int(candidate_bytes[19]) & 0xFF if len(candidate_bytes) > 19 else 0
            header_plausibility = 0
            if 1 <= language_id <= 7:
                header_plausibility += 6
            elif language_id == 0:
                header_plausibility += 2
            else:
                header_plausibility -= 8
            if 0 <= markings <= 0x0F:
                header_plausibility += 2
            else:
                header_plausibility -= 2
            if 0 <= misc_flags <= 0x7F:
                header_plausibility += 1
            else:
                header_plausibility -= 1

            key = personality ^ ot_id
            encrypted = candidate_bytes[32:80]
            if len(encrypted) < 48:
                return None

            decrypted = [0] * 48
            for offset in range(0, 48, 4):
                word = read_u32(encrypted, offset) ^ key
                decrypted[offset] = word & 0xFF
                decrypted[offset + 1] = (word >> 8) & 0xFF
                decrypted[offset + 2] = (word >> 16) & 0xFF
                decrypted[offset + 3] = (word >> 24) & 0xFF

            stored_checksum = int(candidate_bytes[28]) | (int(candidate_bytes[29]) << 8)
            calc_checksum = 0
            for off in range(0, 48, 2):
                calc_checksum = (calc_checksum + read_u16(decrypted, off)) & 0xFFFF
            checksum_matches = int(calc_checksum) == int(stored_checksum)
            if (not checksum_matches) and (not allow_checksum_mismatch_local):
                return None

            order_candidates: List[Tuple[int, int, int, int]] = []
            primary_order = tuple(self.GEN3_PARTY_SUBSTRUCT_ORDERS[personality % 24])
            order_candidates.append(primary_order)
            try:
                alt_order = tuple(self.GEN3_PARTY_SUBSTRUCT_ORDERS_ALT[personality % 24])
                if alt_order not in order_candidates:
                    order_candidates.append(alt_order)
            except Exception:
                pass

            def _decode_with_order(order_tuple: Tuple[int, int, int, int]) -> Optional[Dict[str, object]]:
                growth_offset = order_tuple.index(0) * 12
                attacks_offset = order_tuple.index(1) * 12
                misc_offset = order_tuple.index(3) * 12

                species_internal = read_u16(decrypted, growth_offset)
                if species_internal <= 0 or species_internal > int(max_species_id):
                    return None

                normalized_species = self._normalize_gen3_species_id(species_internal)
                if normalized_species is None or normalized_species <= 0 or normalized_species > int(max_national_species):
                    return None

                level = int(candidate_bytes[84]) if len(candidate_bytes) > 84 else 0
                level_value: Optional[int] = None
                if 0 < level <= 100:
                    level_value = int(level)
                else:
                    return None

                # Party stat sanity helps reject wrong byte-order variants that can still pass checksum/species.
                current_hp = read_u16(candidate_bytes, 86)
                max_hp = read_u16(candidate_bytes, 88)
                if max_hp <= 0 or max_hp > 999:
                    return None
                if current_hp < 0 or current_hp > max_hp:
                    return None

                derived_stats = [
                    read_u16(candidate_bytes, 90),
                    read_u16(candidate_bytes, 92),
                    read_u16(candidate_bytes, 94),
                    read_u16(candidate_bytes, 96),
                    read_u16(candidate_bytes, 98),
                ]
                if any(stat <= 0 or stat > 999 for stat in derived_stats):
                    return None

                move_ids = [
                    read_u16(decrypted, attacks_offset + 0),
                    read_u16(decrypted, attacks_offset + 2),
                    read_u16(decrypted, attacks_offset + 4),
                    read_u16(decrypted, attacks_offset + 6),
                ]
                move_pp = [
                    int(decrypted[attacks_offset + 8 + i]) & 0xFF
                    for i in range(4)
                ]

                move_names: List[str] = []
                plausible_move_count = 0
                invalid_move_count = 0
                for move_id, pp_value in zip(move_ids, move_pp):
                    mid = int(move_id)
                    if mid <= 0:
                        continue
                    rendered = self._resolve_gen3_move_name(mid)
                    move_names.append(rendered)
                    if mid > int(max_known_move_id):
                        invalid_move_count += 1
                        continue
                    if int(pp_value) > 63:
                        invalid_move_count += 1
                        continue
                    plausible_move_count += 1

                iv_ability_word = read_u32(decrypted, misc_offset + 4)
                ability_slot = (iv_ability_word >> 31) & 0x1
                is_egg = ((iv_ability_word >> 30) & 0x1) == 1
                ability_name = self._resolve_gen3_ability_name(int(normalized_species), int(ability_slot))

                nature_name = self.GEN3_NATURE_NAMES[personality % len(self.GEN3_NATURE_NAMES)]
                gender_name = self._resolve_gen3_gender_label(int(normalized_species), int(personality))
                shiny_xor = ((int(ot_id) >> 16) ^ (int(ot_id) & 0xFFFF) ^ (int(personality) >> 16) ^ (int(personality) & 0xFFFF)) & 0xFFFF
                is_shiny = int(shiny_xor) < 8

                held_item_id = read_u16(decrypted, growth_offset + 2)
                experience = read_u32(decrypted, growth_offset + 4)

                plausibility = 0
                if checksum_matches:
                    plausibility += 50
                plausibility += 10
                plausibility += int(header_plausibility)
                plausibility += int(plausible_move_count) * 2
                plausibility -= int(invalid_move_count) * 4
                if isinstance(ability_name, str) and ability_name.strip():
                    plausibility += 2
                if isinstance(gender_name, str) and gender_name not in ("", "Unknown"):
                    plausibility += 1
                if 0 <= int(held_item_id) <= 600:
                    plausibility += 2
                else:
                    plausibility -= 6
                if 0 <= int(experience) <= 2000000:
                    plausibility += 3
                else:
                    plausibility -= 10
                if hint_species_ids:
                    if int(normalized_species) in hint_species_ids:
                        plausibility += 6
                    else:
                        plausibility -= 3

                return {
                    "species": int(species_internal),
                    "normalized_species": int(normalized_species),
                    "level": level_value,
                    "gender": gender_name,
                    "nature": nature_name,
                    "ability": ability_name,
                    "moves": move_names[:4],
                    "shiny": bool(is_shiny),
                    "is_egg": bool(is_egg),
                    "_score": int(plausibility),
                    "_personality": int(personality),
                    "_ot_id": int(ot_id),
                    "_shiny_xor": int(shiny_xor),
                }

            best_details: Optional[Dict[str, object]] = None
            best_score_key: Optional[Tuple[int, int]] = None
            for order_idx, order_tuple in enumerate(order_candidates):
                details = _decode_with_order(order_tuple)
                if details is None:
                    continue
                score_key = (int(details.get("_score", 0)), -int(order_idx))
                if best_score_key is None or score_key > best_score_key:
                    best_score_key = score_key
                    best_details = details

            return best_details

        base_bytes = [int(v) & 0xFF for v in slot_bytes]
        transform_candidates: List[List[int]] = [base_bytes]

        if len(base_bytes) >= 100:
            swapped16 = base_bytes[:]
            for idx in range(0, len(swapped16) - 1, 2):
                swapped16[idx], swapped16[idx + 1] = swapped16[idx + 1], swapped16[idx]
            transform_candidates.append(swapped16)

            swapped32 = base_bytes[:]
            for idx in range(0, len(swapped32) - 3, 4):
                a = swapped32[idx:idx + 4]
                swapped32[idx:idx + 4] = [a[3], a[2], a[1], a[0]]
            transform_candidates.append(swapped32)

        seen_variants = set()
        unique_candidates: List[List[int]] = []
        for variant in transform_candidates:
            key = bytes(variant[:100])
            if key in seen_variants:
                continue
            seen_variants.add(key)
            unique_candidates.append(variant)

        def _choose_best(candidates: List[List[int]], allow_mismatch: bool) -> Optional[Dict[str, object]]:
            best_details: Optional[Dict[str, object]] = None
            best_score_key: Optional[Tuple[int, int]] = None

            for idx, variant in enumerate(candidates):
                details = _decode_once(variant, allow_checksum_mismatch_local=allow_mismatch)
                if details is None:
                    continue
                score = int(details.get("_score", 0))
                score_key = (score, -int(idx))
                if best_score_key is None or score_key > best_score_key:
                    best_score_key = score_key
                    best_details = details

            return best_details

        # Prefer native byte order first. Only try transformed byte orders if
        # base decode fails, to avoid species drift on otherwise valid slots.
        base_candidates: List[List[int]] = [base_bytes]

        strict_details = _choose_best(base_candidates, allow_mismatch=False)
        if strict_details is not None:
            return strict_details

        strict_details = _choose_best(unique_candidates, allow_mismatch=False)
        if strict_details is not None:
            return strict_details

        if allow_checksum_mismatch:
            relaxed_base = _choose_best(base_candidates, allow_mismatch=True)
            if relaxed_base is not None:
                return relaxed_base
            return _choose_best(unique_candidates, allow_mismatch=True)

    def _decode_gen3_party_species(self, slot_bytes: List[int], max_species_id: int, allow_checksum_mismatch: bool = False, species_hint_ids: Optional[Set[int]] = None) -> Optional[int]:
        """Decode species from encrypted Gen 3 party data slot."""
        details = self._decode_gen3_party_slot_details(
            slot_bytes,
            max_species_id=max_species_id,
            allow_checksum_mismatch=allow_checksum_mismatch,
            species_hint_ids=species_hint_ids,
        )
        if not isinstance(details, dict):
            return None
        try:
            species_value = int(details.get("species", 0))
        except (TypeError, ValueError):
            return None
        return species_value if species_value > 0 else None

    def _read_gen3_slot_bytes_for_details(self, slot_addr: int, size: int) -> Optional[List[int]]:
        """Read slot bytes required for details decode without heavy per-byte overhead."""
        try:
            bulk = self.retroarch.read_memory(hex(int(slot_addr)), int(size))
        except Exception:
            bulk = None
        if isinstance(bulk, list) and len(bulk) >= size:
            if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in bulk[:size]):
                return [int(v) & 0xFF for v in bulk[:size]]

        required = list(range(0, 8)) + [28, 29] + list(range(32, 80)) + [84]
        buffer = [0] * max(size, 85)
        for offset in required:
            abs_addr = int(slot_addr) + int(offset)
            value = self.retroarch.read_memory(hex(abs_addr))
            if not isinstance(value, int):
                return None
            buffer[int(offset)] = int(value) & 0xFF
        return buffer

    def _enrich_gen3_party_members(self, party_members: List[Dict], start_addr: str, slot_stride: int, slot_size: int) -> List[Dict]:
        """Attach gender/nature/ability/moves metadata to decoded Gen 3 party members."""
        if not isinstance(party_members, list) or not party_members:
            return party_members

        try:
            base_addr = int(str(start_addr), 16)
            stride = int(slot_stride)
            size = int(slot_size)
        except (TypeError, ValueError):
            return party_members

        if stride <= 0 or size <= 0:
            return party_members

        enriched: List[Dict] = []
        for member in party_members:
            if not isinstance(member, dict):
                enriched.append(member)
                continue

            row = dict(member)
            species_id = 0
            try:
                species_id = int(row.get("id", 0))
            except (TypeError, ValueError):
                species_id = 0

            if species_id > 0:
                row.setdefault("name", self.get_pokemon_name(species_id))

            try:
                slot = int(row.get("slot", 0))
            except (TypeError, ValueError):
                slot = 0
            if slot <= 0:
                enriched.append(row)
                continue

            slot_addr = int(base_addr) + ((int(slot) - 1) * int(stride))
            slot_bytes = self._read_gen3_slot_bytes_for_details(slot_addr, size)
            if not slot_bytes:
                enriched.append(row)
                continue

            details = self._decode_gen3_party_slot_details(
                slot_bytes,
                max_species_id=int(self.GEN3_INTERNAL_SPECIES_MAX),
                allow_checksum_mismatch=True,
            )
            if not isinstance(details, dict):
                enriched.append(row)
                continue

            try:
                detail_species = int(details.get("normalized_species", 0))
            except (TypeError, ValueError):
                detail_species = 0
            if species_id > 0 and detail_species > 0 and detail_species != species_id:
                enriched.append(row)
                continue

            level_value = details.get("level")
            try:
                level_int = int(level_value) if level_value is not None else None
            except (TypeError, ValueError):
                level_int = None
            if level_int is not None and level_int > 0:
                row["level"] = int(level_int)

            for key in ("gender", "nature", "ability"):
                value = details.get(key)
                if isinstance(value, str) and value.strip():
                    row[key] = value.strip()

            moves_value = details.get("moves")
            if isinstance(moves_value, list):
                clean_moves = [
                    str(move).strip()
                    for move in moves_value
                    if isinstance(move, str) and str(move).strip()
                ]
                if clean_moves:
                    row["moves"] = clean_moves[:4]

            enriched.append(row)

        return enriched

    def _read_pokedex_flags(self, start_addr: str, max_pokemon: int, allow_byte_fallback: bool = True) -> List[int]:
        """Read Pokedex bitflags from a start address."""
        if not start_addr:
            return []

        found: List[int] = []
        num_bytes = (max_pokemon + 7) // 8

        # Fast path: read whole bitfield in one command to avoid dozens of round-trips.
        bulk_values = self.retroarch.read_memory(start_addr, num_bytes)
        if isinstance(bulk_values, list) and len(bulk_values) >= num_bytes:
            if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in bulk_values[:num_bytes]):
                for byte_idx, raw_val in enumerate(bulk_values[:num_bytes]):
                    byte_val = int(raw_val) & 0xFF
                    for bit_idx in range(8):
                        pokemon_id = byte_idx * 8 + bit_idx + 1
                        if pokemon_id > max_pokemon:
                            break
                        if (byte_val >> bit_idx) & 1:
                            found.append(pokemon_id)
                return found

        if not allow_byte_fallback:
            return found

        # Compatibility fallback: byte-by-byte reads for cores that do not support bulk memory responses.
        for byte_idx in range(num_bytes):
            addr = hex(int(start_addr, 16) + byte_idx)
            byte_val = self.retroarch.read_memory(addr)
            if not isinstance(byte_val, int):
                continue

            value = int(byte_val) & 0xFF
            for bit_idx in range(8):
                pokemon_id = byte_idx * 8 + bit_idx + 1
                if pokemon_id > max_pokemon:
                    break
                if (value >> bit_idx) & 1:
                    found.append(pokemon_id)

        return found

    def read_pokedex(self, game_name: str, count_hint: Optional[int] = None) -> List[int]:
        """Read Pokedex caught flags with optional count-based sanity selection."""
        config = self.get_game_config(game_name)
        if not config:
            return []

        gen = int(config.get("gen", 1))
        max_pokemon = int(config.get("max_pokemon") or (151 if gen == 1 else (251 if gen == 2 else 386)))
        static_caught_addr = config.get("pokedex_caught", config.get("pokedex_flags", "0xD2F7"))
        static_seen_addr = config.get("pokedex_seen")
        caught_addr = static_caught_addr
        seen_addr = static_seen_addr
        used_pointer_layout = False
        allow_byte_fallback = bool(config.get("pokedex_allow_byte_fallback", 1))
        if bool(getattr(self.retroarch, "is_unstable_io", lambda: False)()):
            allow_byte_fallback = False

        def _safe_read_pokedex_flags(addr: str) -> List[int]:
            """Compatibility wrapper for tests that monkeypatch _read_pokedex_flags."""
            try:
                return self._read_pokedex_flags(addr, max_pokemon, allow_byte_fallback=allow_byte_fallback)
            except TypeError:
                return self._read_pokedex_flags(addr, max_pokemon)
        # Gen 3 should prefer saveblock-pointer reads to avoid static-address cross-layout bleed.
        if gen == 3 and config.get("saveblock2_ptr") and config.get("pokedex_caught_offset") is not None:
            saveblock2_ptr = self._resolve_gen3_saveblock_ptr(config.get("saveblock2_ptr"), game_name=game_name)
            if saveblock2_ptr is not None:
                used_pointer_layout = True
                caught_addr = hex(saveblock2_ptr + int(config.get("pokedex_caught_offset")))
                seen_offset = config.get("pokedex_seen_offset")
                seen_addr = hex(saveblock2_ptr + int(seen_offset)) if seen_offset is not None else seen_addr
            else:
                self._log_pointer_unreadable_throttled(
                    game_name=game_name,
                    pointer=str(config.get("saveblock2_ptr")),
                    layout=config.get("layout_id"),
                )
                if not bool(config.get("pokedex_allow_static_when_pointer_missing", 1)):
                    return []

        caught = _safe_read_pokedex_flags(caught_addr)

        if gen == 3 and used_pointer_layout and not caught and static_caught_addr and static_caught_addr != caught_addr:
            allow_static_fallback = bool(config.get("pokedex_allow_static_fallback", 0))
            if allow_static_fallback:
                fallback_caught = _safe_read_pokedex_flags(static_caught_addr)
                if fallback_caught:
                    log_event(
                        logging.INFO,
                        "gen3_pointer_fallback_static",
                        game=game_name,
                        kind="pokedex",
                        pointer_addr=caught_addr,
                        static_addr=static_caught_addr,
                        count=len(fallback_caught),
                    )
                    caught = fallback_caught
                    seen_addr = static_seen_addr
            else:
                self._log_pointer_fallback_skipped_throttled(
                    game_name=game_name,
                    kind="pokedex",
                    pointer_addr=caught_addr,
                    static_addr=static_caught_addr,
                )

        # For Gen 3, always trust the caught bitset for unlock checks.
        # Count hints in achievement JSON can represent seen counts and cause false unlocks.
        if gen == 3:
            if seen_addr:
                seen = _safe_read_pokedex_flags(seen_addr)
                if seen and len(caught) > len(seen):
                    gap = len(caught) - len(seen)
                    try:
                        warning_gap = max(10, int(config.get("pokedex_seen_warning_gap", 10)))
                    except (TypeError, ValueError):
                        warning_gap = 10
                    if gap >= warning_gap:
                        key = str(game_name or "").strip().lower() or "unknown"
                        now = time.monotonic()
                        last = float(self._pokedex_seen_less_last_log.get(key, 0.0))
                        if (now - last) >= 60.0:
                            self._pokedex_seen_less_last_log[key] = now
                            log_event(
                                logging.WARNING,
                                "pokedex_seen_less_than_caught",
                                game=game_name,
                                layout=config.get("layout_id"),
                                caught_count=len(caught),
                                seen_count=len(seen),
                                gap=gap,
                            )
            return caught

        if count_hint is None or not seen_addr or seen_addr == caught_addr:
            return caught

        seen = _safe_read_pokedex_flags(seen_addr)
        candidates = [("caught", caught)]
        if seen:
            candidates.append(("seen", seen))

        best_name, best_list = min(
            candidates,
            key=lambda item: (abs(len(item[1]) - int(count_hint)), 0 if item[0] == "caught" else 1),
        )

        if best_name != "caught":
            log_event(
                logging.INFO,
                "pokedex_source_adjusted",
                game=game_name,
                selected=best_name,
                count_hint=count_hint,
                caught_count=len(caught),
                seen_count=len(seen),
            )

        return best_list
    
    def read_party(self, game_name: str, caught_ids_hint: Optional[Set[int]] = None) -> List[Dict]:
        """Read current party Pokemon"""
        config = self.get_game_config(game_name)
        if not config:
            self._last_party_read_meta = {
                "game": game_name,
                "generation": None,
                "expected_count": None,
                "decoded_count": 0,
                "incomplete": False,
                "count_addr": None,
                "start_addr": None,
                "stride": None,
                "budget_hit": False,
                "reason": "missing_config",
            }
            return []

        caught_ids_set: Set[int] = set()
        if isinstance(caught_ids_hint, (set, list, tuple)):
            for raw_id in caught_ids_hint:
                try:
                    pokemon_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if pokemon_id > 0:
                    caught_ids_set.add(pokemon_id)
        use_caught_plausibility = len(caught_ids_set) >= 5

        gen = int(config.get("gen", 1))
        self._last_party_read_meta = {
            "game": game_name,
            "generation": int(gen),
            "expected_count": None,
            "decoded_count": 0,
            "incomplete": False,
            "count_addr": None,
            "start_addr": None,
            "stride": int(config.get("party_slot_size", 0) or 0),
            "budget_hit": False,
            "reason": None,
        }
        party = []
        static_party_count_addr = config["party_count"]
        static_party_start_addr = config["party_start"]
        party_count_addr = static_party_count_addr
        party_start_addr = static_party_start_addr
        slot_size = int(config["party_slot_size"])
        used_pointer_layout = False

        # Gen 3 should prefer saveblock-pointer party addresses across all layouts.
        if gen == 3 and bool(config.get("party_use_pointer_layout", 0)) and config.get("saveblock1_ptr") and config.get("party_count_offset") is not None and config.get("party_start_offset") is not None:
            saveblock1_ptr = self._resolve_gen3_saveblock_ptr(config.get("saveblock1_ptr"), game_name=game_name)
            if saveblock1_ptr is not None:
                used_pointer_layout = True
                party_count_addr = hex(saveblock1_ptr + int(config.get("party_count_offset")))
                party_start_addr = hex(saveblock1_ptr + int(config.get("party_start_offset")))
            else:
                self._log_pointer_unreadable_throttled(
                    game_name=game_name,
                    pointer=str(config.get("saveblock1_ptr")),
                    layout=config.get("layout_id"),
                )
                if not bool(config.get("party_allow_static_when_pointer_missing", 1)):
                    self._last_party_read_meta.update({
                        "expected_count": None,
                        "decoded_count": 0,
                        "incomplete": False,
                        "count_addr": str(party_count_addr),
                        "start_addr": str(party_start_addr),
                        "stride": int(slot_size),
                        "budget_hit": False,
                        "reason": "saveblock_pointer_unreadable",
                    })
                    return []

        # Read party count from selected layout.
        count = self.retroarch.read_memory(party_count_addr)
        if (not isinstance(count, int) or count < 0 or count > 6) and used_pointer_layout:
            fallback_count = self.retroarch.read_memory(static_party_count_addr)
            if isinstance(fallback_count, int) and 0 <= fallback_count <= 6:
                log_event(
                    logging.INFO,
                    "gen3_pointer_fallback_static",
                    game=game_name,
                    kind="party",
                    pointer_addr=party_count_addr,
                    static_addr=static_party_count_addr,
                    count=fallback_count,
                )
                count = fallback_count
                party_count_addr = static_party_count_addr
                party_start_addr = static_party_start_addr

        count_valid = isinstance(count, int) and 0 <= int(count) <= 6
        max_species_id = max(self.POKEMON_NAMES.keys())
        max_decode_species_id = int(self.GEN3_INTERNAL_SPECIES_MAX) if gen == 3 else max_species_id

        if gen == 3 and not count_valid and bool(config.get("party_skip_scan_on_invalid_count", 0)):
            self._last_party_read_meta.update({
                "expected_count": None,
                "decoded_count": 0,
                "incomplete": False,
                "count_addr": str(party_count_addr),
                "start_addr": str(party_start_addr),
                "stride": int(slot_size),
                "budget_hit": False,
                "reason": "invalid_party_count",
            })
            return []

        if gen == 3:
            force_gen3_party_byte_reads = bool(config.get("party_force_byte_reads", 0))
            allow_party_byte_fallback = bool(config.get("party_allow_byte_fallback", 1))
            ignore_party_count = bool(config.get("party_ignore_count", 0))
            enable_offset_scan = bool(config.get("party_enable_offset_scan", 1))
            allow_double_stride = bool(config.get("party_allow_double_stride", 1))
            try_double_bulk = bool(config.get("party_try_double_bulk", 1))
            try:
                party_decode_budget_ms = max(200, int(config.get("party_decode_budget_ms", 1200)))
            except (TypeError, ValueError):
                party_decode_budget_ms = 1200
            decode_deadline = time.perf_counter() + (float(party_decode_budget_ms) / 1000.0)
            budget_exceeded = False
            gen3_required_slot_bytes = list(range(0, 8)) + [28, 29] + list(range(32, 80)) + [84]

            try:
                primary_count_addr = hex(int(str(party_count_addr), 16))
                primary_start_addr = hex(int(str(party_start_addr), 16))
            except (TypeError, ValueError):
                self._last_party_read_meta.update({
                    "count_addr": str(party_count_addr),
                    "start_addr": str(party_start_addr),
                    "reason": "invalid_party_addresses",
                })
                return []

            def _decode_budget_exceeded() -> bool:
                return time.perf_counter() >= decode_deadline

            address_pairs: List[Tuple[str, str]] = [(primary_count_addr, primary_start_addr)]
            if not used_pointer_layout:
                raw_count_candidates = config.get("party_count_candidates")
                raw_start_candidates = config.get("party_start_candidates")

                count_candidates: List[str] = [primary_count_addr]
                if isinstance(raw_count_candidates, list):
                    for candidate in raw_count_candidates:
                        if isinstance(candidate, str):
                            count_candidates.append(candidate)

                start_candidates: List[str] = [primary_start_addr]
                if isinstance(raw_start_candidates, list):
                    for candidate in raw_start_candidates:
                        if isinstance(candidate, str):
                            start_candidates.append(candidate)

                # Preserve legacy indexed pairing first.
                for idx, start_candidate in enumerate(start_candidates):
                    count_candidate = count_candidates[idx] if idx < len(count_candidates) else primary_count_addr
                    address_pairs.append((count_candidate, start_candidate))

                # Cross-pair count and start candidates to avoid locking to a bad count address.
                for start_candidate in start_candidates:
                    for count_candidate in count_candidates:
                        address_pairs.append((count_candidate, start_candidate))

                # Derive nearby count candidates from each start address.
                # Emerald pointer layout uses count at (start - 0x4); some cores shift by one byte.
                for start_candidate in start_candidates:
                    try:
                        start_base = int(str(start_candidate), 16)
                    except (TypeError, ValueError):
                        continue
                    for delta in (-4, -3):
                        address_pairs.append((hex(start_base + delta), start_candidate))

            seen_pairs = set()
            ordered_pairs: List[Tuple[str, str]] = []
            for count_candidate, start_candidate in address_pairs:
                try:
                    normalized_count = hex(int(str(count_candidate), 16))
                    normalized_start = hex(int(str(start_candidate), 16))
                except (TypeError, ValueError):
                    continue
                pair_key = (normalized_count, normalized_start)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                ordered_pairs.append(pair_key)

            if not ordered_pairs:
                self._last_party_read_meta.update({
                    "count_addr": str(party_count_addr),
                    "start_addr": str(party_start_addr),
                    "reason": "no_candidate_pairs",
                })
                return []

            try:
                max_pairs = max(1, int(config.get("party_max_pairs", len(ordered_pairs))))
            except (TypeError, ValueError):
                max_pairs = len(ordered_pairs)
            ordered_pairs = ordered_pairs[:max_pairs]

            count_cache: Dict[str, object] = {}
            def _read_count_candidate(candidate_addr: str) -> object:
                cached = count_cache.get(candidate_addr, None)
                if cached is not None:
                    return cached
                if candidate_addr == primary_count_addr and count_valid:
                    value = int(count)
                else:
                    value = self.retroarch.read_memory(candidate_addr)
                count_cache[candidate_addr] = value
                return value

            if bool(config.get("party_skip_scan_on_zero_count", 0)) and not ignore_party_count:
                valid_counts: List[int] = []
                for candidate_count_addr, _ in ordered_pairs:
                    candidate_value = _read_count_candidate(candidate_count_addr)
                    if isinstance(candidate_value, int) and 0 <= int(candidate_value) <= 6:
                        valid_counts.append(int(candidate_value))
                if valid_counts and max(valid_counts) == 0:
                    self._last_party_read_meta.update({
                        "expected_count": 0,
                        "decoded_count": 0,
                        "incomplete": False,
                        "count_addr": str(primary_count_addr),
                        "start_addr": str(primary_start_addr),
                        "stride": int(slot_size),
                        "budget_hit": False,
                        "reason": "zero_party_count",
                    })
                    return []

            best_party: List[Dict] = []
            best_raw_party_len = 0
            best_raw_slots: List[int] = []
            best_base = int(ordered_pairs[0][1], 16)
            best_count_addr = ordered_pairs[0][0]
            best_start_addr = ordered_pairs[0][1]
            best_stride = int(slot_size)
            best_expected_count = int(count) if count_valid else None
            best_score: Tuple[int, ...] = (
                -1, -1, -10**9, -10**9, -1, -1, -1, -1, -10**9, -10**9, -10**9, -10**9, -10**9, -10**9, -10**9
            )
            perfect_candidate_found = False


            def _decode_party_candidate(base_addr: int, slot_stride: int, slot_count: int, allow_relaxed_species: bool = False) -> Tuple[List[Dict], int]:
                decoded_party: List[Dict] = []
                decode_failures = 0

                def _decode_species(slot_data: List[int]) -> Optional[int]:
                    decoder = self._decode_gen3_party_species
                    call_variants = (
                        lambda: decoder(
                            slot_data,
                            max_species_id=max_decode_species_id,
                            allow_checksum_mismatch=allow_relaxed_species,
                        ),
                        lambda: decoder(
                            slot_data,
                            max_species_id=max_decode_species_id,
                            allow_checksum_mismatch=allow_relaxed_species,
                        ),
                        lambda: decoder(
                            slot_data,
                            max_species_id=max_decode_species_id,
                        ),
                        lambda: decoder(slot_data, max_decode_species_id),
                    )
                    for call in call_variants:
                        try:
                            return call()
                        except TypeError:
                            continue
                    return None

                def _normalize_species(species_value: int) -> Optional[int]:
                    normalized_species = self._normalize_gen3_species_id(species_value)
                    if normalized_species is None:
                        return None
                    if normalized_species <= 0 or normalized_species > max_species_id:
                        return None
                    return int(normalized_species)

                def _build_member(slot_data: List[int], normalized_species: int, slot_idx: int, details: Optional[Dict[str, object]] = None) -> Dict[str, object]:
                    level = slot_data[84] if len(slot_data) > 84 and int(slot_data[84]) > 0 else None
                    member: Dict[str, object] = {
                        "id": int(normalized_species),
                        "level": int(level) if level is not None else None,
                        "slot": int(slot_idx) + 1,
                        "name": self.get_pokemon_name(int(normalized_species)),
                    }

                    resolved_details = details if isinstance(details, dict) else self._decode_gen3_party_slot_details(
                        slot_data,
                        max_species_id=max_decode_species_id,
                        allow_checksum_mismatch=allow_relaxed_species,
                        species_hint_ids={int(normalized_species)},
                    )
                    if isinstance(resolved_details, dict):
                        try:
                            detail_norm = int(resolved_details.get("normalized_species", 0))
                        except (TypeError, ValueError):
                            detail_norm = 0
                        if detail_norm in (0, int(normalized_species)):
                            for key in ("gender", "nature", "ability"):
                                value = resolved_details.get(key)
                                if isinstance(value, str) and value.strip():
                                    member[key] = value.strip()
                            member["shiny"] = bool(resolved_details.get("shiny", False))
                            member["is_egg"] = bool(resolved_details.get("is_egg", False))
                            moves = resolved_details.get("moves")
                            if isinstance(moves, list):
                                clean_moves = [
                                    str(move).strip()
                                    for move in moves
                                    if isinstance(move, str) and str(move).strip()
                                ]
                                if clean_moves:
                                    member["moves"] = clean_moves[:4]
                            try:
                                member["_shiny_xor"] = int(resolved_details.get("_shiny_xor", -1))
                            except (TypeError, ValueError):
                                pass
                            try:
                                member["_personality"] = int(resolved_details.get("_personality")) & 0xFFFFFFFF
                            except (TypeError, ValueError):
                                pass
                            try:
                                member["_ot_id"] = int(resolved_details.get("_ot_id")) & 0xFFFFFFFF
                            except (TypeError, ValueError):
                                pass

                    shiny_pid: Optional[int] = None
                    shiny_ot: Optional[int] = None
                    if isinstance(resolved_details, dict):
                        try:
                            shiny_pid = int(resolved_details.get("_personality")) & 0xFFFFFFFF
                        except (TypeError, ValueError):
                            shiny_pid = None
                        try:
                            shiny_ot = int(resolved_details.get("_ot_id")) & 0xFFFFFFFF
                        except (TypeError, ValueError):
                            shiny_ot = None

                    # Fallback only if decode details did not provide PID/OTID.
                    if shiny_pid is None or shiny_ot is None:
                        try:
                            if isinstance(slot_data, list) and len(slot_data) >= 8:
                                shiny_pid = (int(slot_data[0]) | (int(slot_data[1]) << 8) | (int(slot_data[2]) << 16) | (int(slot_data[3]) << 24)) & 0xFFFFFFFF
                                shiny_ot = (int(slot_data[4]) | (int(slot_data[5]) << 8) | (int(slot_data[6]) << 16) | (int(slot_data[7]) << 24)) & 0xFFFFFFFF
                        except Exception:
                            shiny_pid = None
                            shiny_ot = None

                    try:
                        if shiny_pid is not None and shiny_ot is not None:
                            member["_personality"] = int(shiny_pid) & 0xFFFFFFFF
                            member["_ot_id"] = int(shiny_ot) & 0xFFFFFFFF
                            shiny_value = self._gen3_shiny_value(shiny_pid, shiny_ot)
                            if shiny_value is not None:
                                member["shiny"] = int(shiny_value) < 8
                                member["_shiny_xor"] = int(shiny_value)
                    except Exception:
                        pass

                    return member
                def _select_best_slot_variant(variants: List[List[int]]) -> Tuple[Optional[List[int]], Optional[int], Optional[Dict[str, object]]]:
                    best_variant: Optional[List[int]] = None
                    best_species: Optional[int] = None
                    best_details: Optional[Dict[str, object]] = None
                    best_score_key: Optional[Tuple[int, int]] = None

                    for idx, variant in enumerate(variants):
                        details = self._decode_gen3_party_slot_details(
                            variant,
                            max_species_id=max_decode_species_id,
                            allow_checksum_mismatch=allow_relaxed_species,
                        )
                        if not isinstance(details, dict):
                            continue
                        try:
                            normalized_species = int(details.get("normalized_species", 0) or 0)
                        except (TypeError, ValueError):
                            normalized_species = 0
                        if normalized_species <= 0 or normalized_species > max_species_id:
                            continue
                        score_key = (int(details.get("_score", 0)), -int(idx))
                        if best_score_key is None or score_key > best_score_key:
                            best_score_key = score_key
                            best_variant = variant
                            best_species = int(normalized_species)
                            best_details = details

                    if best_variant is not None and best_species is not None:
                        return best_variant, int(best_species), best_details

                    for variant in variants:
                        species_id = _decode_species(variant)
                        if species_id is None:
                            continue
                        normalized_species = _normalize_species(species_id)
                        if normalized_species is None:
                            continue
                        return variant, int(normalized_species), None
                    return None, None, None


                # Fast path: read contiguous party block once.
                if not force_gen3_party_byte_reads and slot_count > 0 and slot_stride > 0:
                    total_len = int(slot_count) * int(slot_stride)
                    if total_len > 0 and total_len <= 2048:
                        block_values = self.retroarch.read_memory(hex(base_addr), total_len)
                        if isinstance(block_values, list) and len(block_values) >= total_len:
                            if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in block_values[:total_len]):
                                for slot_idx in range(slot_count):
                                    if _decode_budget_exceeded():
                                        return decoded_party, decode_failures
                                    offset = int(slot_idx) * int(slot_stride)
                                    if len(block_values) < offset + int(slot_size):
                                        decode_failures += 1
                                        continue
                                    slot_data = [int(v) & 0xFF for v in block_values[offset:offset + int(slot_size)]]
                                    selected_slot_data, selected_species, selected_details = _select_best_slot_variant([slot_data])
                                    if selected_slot_data is None or selected_species is None:
                                        decode_failures += 1
                                        continue
                                    decoded_party.append(_build_member(selected_slot_data, int(selected_species), slot_idx, details=selected_details))
                                # Only short-circuit on a complete decode; partial bulk reads can
                                # be misleading on some cores, so fall through to per-slot recovery.
                                if len(decoded_party) >= int(slot_count):
                                    return decoded_party, decode_failures

                    # Interleaved/word-oriented fallback: read 2x bytes and de-interleave even/odd streams.
                    if try_double_bulk and (total_len * 2) <= 4096:
                        block_double = self.retroarch.read_memory(hex(base_addr), total_len * 2)
                        if isinstance(block_double, list) and len(block_double) >= (total_len * 2):
                            if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in block_double[:total_len * 2]):
                                best_variant_party: List[Dict] = []
                                best_variant_failures = slot_count
                                for variant_block in (
                                    [int(v) & 0xFF for v in block_double[:total_len * 2:2]],
                                    [int(v) & 0xFF for v in block_double[1:total_len * 2:2]],
                                ):
                                    variant_party: List[Dict] = []
                                    variant_failures = 0
                                    for slot_idx in range(slot_count):
                                        if _decode_budget_exceeded():
                                            break
                                        offset = int(slot_idx) * int(slot_stride)
                                        if len(variant_block) < offset + int(slot_size):
                                            variant_failures += 1
                                            continue
                                        slot_data = variant_block[offset:offset + int(slot_size)]
                                        selected_slot_data, selected_species, selected_details = _select_best_slot_variant([slot_data])
                                        if selected_slot_data is None or selected_species is None:
                                            variant_failures += 1
                                            continue
                                        variant_party.append(_build_member(selected_slot_data, int(selected_species), slot_idx, details=selected_details))
                                    if len(variant_party) > len(best_variant_party):
                                        best_variant_party = variant_party
                                        best_variant_failures = variant_failures
                                if best_variant_party:
                                    # As above, only short-circuit if fully decoded.
                                    if len(best_variant_party) >= int(slot_count):
                                        return best_variant_party, best_variant_failures

                # Bulk paths found only a partial decode; retry clean per-slot reads.
                if decoded_party:
                    decoded_party = []
                    decode_failures = 0

                for slot_idx in range(slot_count):
                    if _decode_budget_exceeded():
                        return decoded_party, decode_failures

                    slot_addr = hex(base_addr + (slot_idx * slot_stride))
                    slot_data_variants: List[List[int]] = []

                    if not force_gen3_party_byte_reads:
                        bulk_slot_data = self.retroarch.read_memory(slot_addr, slot_size)
                        if isinstance(bulk_slot_data, list) and len(bulk_slot_data) >= slot_size:
                            if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in bulk_slot_data[:slot_size]):
                                slot_data_variants.append([int(v) & 0xFF for v in bulk_slot_data[:slot_size]])

                        if try_double_bulk:
                            # Some cores expose 16-bit-oriented reads; try de-interleaving a 2x block.
                            bulk_double = self.retroarch.read_memory(slot_addr, slot_size * 2)
                            if isinstance(bulk_double, list) and len(bulk_double) >= slot_size * 2:
                                if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in bulk_double[:slot_size * 2]):
                                    even_bytes = [int(v) & 0xFF for v in bulk_double[:slot_size * 2:2]]
                                    odd_bytes = [int(v) & 0xFF for v in bulk_double[1:slot_size * 2:2]]
                                    slot_data_variants.append(even_bytes)
                                    slot_data_variants.append(odd_bytes)
                    selected_slot_data, selected_species, selected_details = _select_best_slot_variant(slot_data_variants)

                    # If bulk reads are present but fail checksum/decode, retry with direct byte reads.
                    if (selected_slot_data is None or selected_species is None) and allow_party_byte_fallback:
                        slot_data_low = [0] * 85
                        slot_data_high = [0] * 85
                        slot_data_addrle = [0] * 85
                        slot_data_addrbe = [0] * 85
                        saw_wide_values = False
                        for byte_idx in gen3_required_slot_bytes:
                            if _decode_budget_exceeded():
                                return decoded_party, decode_failures
                            abs_addr = base_addr + (slot_idx * slot_stride) + int(byte_idx)
                            byte_val = self.retroarch.read_memory(hex(abs_addr))
                            if not isinstance(byte_val, int):
                                slot_data_low = []
                                slot_data_high = []
                                slot_data_addrle = []
                                slot_data_addrbe = []
                                break

                            raw_val = int(byte_val)
                            if raw_val > 0xFF:
                                saw_wide_values = True

                            low_byte = raw_val & 0xFF
                            high_byte = (raw_val >> 8) & 0xFF
                            le_shift = (int(abs_addr) & 0x3) * 8
                            be_shift = (3 - (int(abs_addr) & 0x3)) * 8

                            slot_data_low[int(byte_idx)] = low_byte
                            slot_data_high[int(byte_idx)] = high_byte
                            slot_data_addrle[int(byte_idx)] = (raw_val >> le_shift) & 0xFF
                            slot_data_addrbe[int(byte_idx)] = (raw_val >> be_shift) & 0xFF

                        slot_data_candidates: List[List[int]] = []
                        if slot_data_low:
                            slot_data_candidates.append(slot_data_low)
                            if saw_wide_values:
                                slot_data_candidates.extend([slot_data_addrle, slot_data_high, slot_data_addrbe])

                        deduped_slot_data_candidates: List[List[int]] = []
                        seen_variant_keys = set()
                        for slot_variant in slot_data_candidates:
                            variant_key = bytes(int(v) & 0xFF for v in slot_variant[:85])
                            if variant_key in seen_variant_keys:
                                continue
                            seen_variant_keys.add(variant_key)
                            deduped_slot_data_candidates.append(slot_variant)

                        if selected_slot_data is None or selected_species is None:
                            selected_slot_data, selected_species, selected_details = _select_best_slot_variant(deduped_slot_data_candidates)

                    if selected_slot_data is None or selected_species is None:
                        decode_failures += 1
                        continue

                    decoded_party.append(_build_member(selected_slot_data, int(selected_species), slot_idx, details=selected_details))
                return decoded_party, decode_failures

            for count_candidate, start_candidate in ordered_pairs:
                if _decode_budget_exceeded():
                    budget_exceeded = True
                    break

                local_count = _read_count_candidate(count_candidate)
                local_count_valid = isinstance(local_count, int) and 0 <= int(local_count) <= 6

                if ignore_party_count:
                    if local_count_valid and int(local_count) == 0:
                        slots_to_scan = 0
                    else:
                        slots_to_scan = 6
                else:
                    if local_count_valid:
                        if int(local_count) > 0:
                            slots_to_scan = int(local_count)
                        elif bool(config.get("party_skip_scan_on_zero_count", 0)):
                            slots_to_scan = 0
                        else:
                            slots_to_scan = 6
                    else:
                        slots_to_scan = 6

                if int(slots_to_scan) <= 0:
                    continue

                try:
                    start_base = int(start_candidate, 16)
                except (TypeError, ValueError):
                    continue

                base_candidates: List[int] = [start_base]
                if not used_pointer_layout and enable_offset_scan:
                    for off in (4, -4, 8, -8, slot_size, -slot_size):
                        cand = start_base + off
                        if cand > 0:
                            base_candidates.append(cand)

                seen_bases = set()
                ordered_bases: List[int] = []
                for base in base_candidates:
                    if base in seen_bases:
                        continue
                    seen_bases.add(base)
                    ordered_bases.append(base)

                stride_candidates: List[int] = []
                configured_stride_candidates = config.get("party_stride_candidates")
                if isinstance(configured_stride_candidates, list):
                    for candidate in configured_stride_candidates:
                        try:
                            stride_candidates.append(int(candidate))
                        except (TypeError, ValueError):
                            continue
                if not stride_candidates:
                    stride_candidates = [int(slot_size)]
                    if not used_pointer_layout and allow_double_stride and int(slot_size) > 0:
                        stride_candidates.append(int(slot_size) * 2)

                seen_strides = set()
                ordered_strides: List[int] = []
                for stride in stride_candidates:
                    if int(stride) <= 0 or int(stride) in seen_strides:
                        continue
                    seen_strides.add(int(stride))
                    ordered_strides.append(int(stride))

                for base in ordered_bases:
                    if _decode_budget_exceeded():
                        budget_exceeded = True
                        break
                    for slot_stride in ordered_strides:
                        if _decode_budget_exceeded():
                            budget_exceeded = True
                            break

                        candidate_party, failures = _decode_party_candidate(base, slot_stride, int(slots_to_scan))

                        slot_numbers = [
                            int(member.get("slot", 0))
                            for member in candidate_party
                            if int(member.get("slot", 0)) > 0
                        ]
                        contiguous_prefix_len = 0
                        for slot_number in slot_numbers:
                            if slot_number == contiguous_prefix_len + 1:
                                contiguous_prefix_len += 1
                            else:
                                break

                        normalized_party = candidate_party[:contiguous_prefix_len]
                        non_prefix_slots = max(0, len(slot_numbers) - contiguous_prefix_len)
                        starts_at_one = 1 if slot_numbers and slot_numbers[0] == 1 else 0
                        contiguous_only = 1 if slot_numbers and non_prefix_slots == 0 else 0

                        gap_penalty = 0
                        first_slot = 99
                        if slot_numbers:
                            first_slot = slot_numbers[0]
                            expected = list(range(first_slot, first_slot + len(slot_numbers)))
                            gap_penalty = sum(1 for actual, exp in zip(slot_numbers, expected) if actual != exp)

                        count_bonus = 0
                        count_exact = 0
                        count_mismatch = 0
                        if local_count_valid and int(local_count) > 0:
                            count_bonus = 1
                            count_mismatch = abs(contiguous_prefix_len - int(local_count))
                            if contiguous_prefix_len == int(local_count):
                                count_exact = 1

                        caught_overlap = contiguous_prefix_len
                        caught_unknown = 0
                        caught_bonus = 0
                        if use_caught_plausibility and contiguous_prefix_len > 0:
                            caught_bonus = 1
                            caught_overlap = sum(
                                1
                                for member in normalized_party
                                if int(member.get("id", 0)) in caught_ids_set
                            )
                            caught_unknown = max(0, contiguous_prefix_len - int(caught_overlap))

                        base_penalty = abs(int(base) - int(start_base))
                        stride_penalty = abs(int(slot_stride) - int(slot_size))

                        # Prefer a contiguous 1..N prefix, then count agreement and minimal fallback deviation.
                        # When we have a stable caught list, also prefer party candidates that are actually caught.
                        score = (
                            count_exact,
                            caught_bonus,
                            caught_overlap,
                            -caught_unknown,
                            contiguous_prefix_len,
                            contiguous_only,
                            starts_at_one,
                            count_bonus,
                            -count_mismatch,
                            -non_prefix_slots,
                            -failures,
                            -gap_penalty,
                            -base_penalty,
                            -stride_penalty,
                            len(candidate_party),
                        )

                        if score > best_score:
                            best_score = score
                            best_base = base
                            best_stride = int(slot_stride)
                            best_party = normalized_party
                            best_raw_party_len = len(candidate_party)
                            best_raw_slots = slot_numbers
                            best_count_addr = count_candidate
                            best_start_addr = start_candidate
                            best_expected_count = int(local_count) if local_count_valid else None

                            if (
                                count_exact == 1
                                and contiguous_only == 1
                                and int(failures) == 0
                                and int(base) == int(start_base)
                                and int(slot_stride) == int(slot_size)
                                and str(count_candidate) == str(primary_count_addr)
                                and str(start_candidate) == str(primary_start_addr)
                            ):
                                perfect_candidate_found = True

                        if perfect_candidate_found:
                            break

                    if budget_exceeded or perfect_candidate_found:
                        break
                if budget_exceeded or perfect_candidate_found:
                    break

                if budget_exceeded or perfect_candidate_found:
                    break
            # If fallback search settled on a non-canonical stride/base with an incomplete decode,
            # retry the canonical static layout directly before accepting fallback output.
            if (
                isinstance(best_expected_count, int)
                and int(best_expected_count) > 0
                and len(best_party) < int(best_expected_count)
                and int(best_stride) != int(slot_size)
            ):
                try:
                    canonical_base = int(primary_start_addr, 16)
                except (TypeError, ValueError):
                    canonical_base = None

                if canonical_base is not None:
                    canonical_party, canonical_failures = _decode_party_candidate(canonical_base, int(slot_size), int(best_expected_count))
                    canonical_slots = [
                        int(member.get("slot", 0))
                        for member in canonical_party
                        if int(member.get("slot", 0)) > 0
                    ]
                    canonical_prefix_len = 0
                    for slot_number in canonical_slots:
                        if slot_number == canonical_prefix_len + 1:
                            canonical_prefix_len += 1
                        else:
                            break
                    canonical_normalized = canonical_party[:canonical_prefix_len]

                    if len(canonical_normalized) > len(best_party):
                        best_party = canonical_normalized
                        best_raw_party_len = len(canonical_party)
                        best_raw_slots = canonical_slots
                        best_base = int(canonical_base)
                        best_start_addr = primary_start_addr
                        best_stride = int(slot_size)
                        best_count_addr = primary_count_addr
                        log_event(
                            logging.INFO,
                            "gen3_party_canonical_recovered",
                            game=game_name,
                            decoded=len(best_party),
                            expected=best_expected_count,
                            base=hex(int(best_base)),
                            stride=int(best_stride),
                            failures=int(canonical_failures),
                        )

            if budget_exceeded:
                log_event(
                    logging.INFO,
                    "gen3_party_decode_budget_hit",
                    game=game_name,
                    budget_ms=party_decode_budget_ms,
                    decoded=len(best_party),
                    expected=best_expected_count,
                    start_addr=best_start_addr,
                    count_addr=best_count_addr,
                )

            interleaved_recovery_meta: Optional[Dict[str, object]] = None
            interleaved_recovery_miss_meta: Optional[Dict[str, object]] = None
            # Recover interleaved half-party candidates (e.g. Emerald 3/6 at stride 200).
            if (
                best_party
                and isinstance(best_expected_count, int)
                and int(best_expected_count) > 1
                and len(best_party) * 2 == int(best_expected_count)
                and int(best_stride) == int(slot_size) * 2
            ):
                companion_seed_bases: List[int] = []
                for companion_base in (int(best_base) - int(slot_size), int(best_base) + int(slot_size)):
                    if int(companion_base) > 0 and int(companion_base) != int(best_base):
                        companion_seed_bases.append(int(companion_base))

                raw_partner_start_candidates = config.get("party_start_candidates")
                if isinstance(raw_partner_start_candidates, list):
                    for candidate in raw_partner_start_candidates:
                        try:
                            candidate_base = int(str(candidate), 16)
                        except (TypeError, ValueError):
                            continue
                        if candidate_base > 0 and candidate_base != int(best_base):
                            companion_seed_bases.append(int(candidate_base))

                companion_bases: List[int] = []
                seen_companion_bases = set()
                # Probe near each companion seed for byte-shifted/interleaved alignments.
                for seed_base in companion_seed_bases:
                    for jitter in (0, 1, -1, 2, -2, 4, -4, 8, -8):
                        candidate = int(seed_base) + int(jitter)
                        if candidate <= 0 or candidate == int(best_base) or candidate in seen_companion_bases:
                            continue
                        seen_companion_bases.add(candidate)
                        companion_bases.append(candidate)

                partner_party: List[Dict] = []
                partner_base: Optional[int] = None
                partner_failures = 10**9
                partner_raw_len = 0
                partner_raw_slots: List[int] = []
                interleaved_probe_results: List[Dict[str, int]] = []

                # Reserve a small dedicated budget for half-party recovery even after main scan hits budget.
                recovery_saved_deadline = decode_deadline
                decode_deadline = max(float(decode_deadline), time.perf_counter() + 1.2)
                try:
                    for companion_base in companion_bases:
                        candidate_party, candidate_failures = _decode_party_candidate(companion_base, int(best_stride), int(best_expected_count), allow_relaxed_species=True)
                        slot_numbers = [
                            int(member.get("slot", 0))
                            for member in candidate_party
                            if int(member.get("slot", 0)) > 0
                        ]
                        contiguous_prefix_len = 0
                        for slot_number in slot_numbers:
                            if slot_number == contiguous_prefix_len + 1:
                                contiguous_prefix_len += 1
                            else:
                                break

                        normalized_partner = candidate_party[:contiguous_prefix_len]
                        interleaved_probe_results.append({
                            "base": int(companion_base),
                            "raw": len(candidate_party),
                            "normalized": len(normalized_partner),
                            "failures": int(candidate_failures),
                        })
                        if not normalized_partner:
                            continue

                        if (
                            len(normalized_partner) > len(partner_party)
                            or (
                                len(normalized_partner) == len(partner_party)
                                and int(candidate_failures) < int(partner_failures)
                            )
                        ):
                            partner_party = normalized_partner
                            partner_base = int(companion_base)
                            partner_failures = int(candidate_failures)
                            partner_raw_len = len(candidate_party)
                            partner_raw_slots = slot_numbers
                finally:
                    decode_deadline = recovery_saved_deadline

                if partner_party and partner_base is not None:
                    if int(best_base) <= int(partner_base):
                        low_phase = best_party
                        high_phase = partner_party
                    else:
                        low_phase = partner_party
                        high_phase = best_party

                    merged_party: List[Dict] = []
                    max_phase_len = max(len(low_phase), len(high_phase))
                    for slot_idx in range(max_phase_len):
                        if slot_idx < len(low_phase):
                            member = dict(low_phase[slot_idx])
                            member["slot"] = len(merged_party) + 1
                            merged_party.append(member)
                        if slot_idx < len(high_phase):
                            member = dict(high_phase[slot_idx])
                            member["slot"] = len(merged_party) + 1
                            merged_party.append(member)

                    merged_party = merged_party[:int(best_expected_count)]
                    if len(merged_party) == int(best_expected_count):
                        original_base = int(best_base)
                        original_stride = int(best_stride)
                        best_party = merged_party
                        best_raw_party_len = max(best_raw_party_len, partner_raw_len, len(merged_party))
                        best_raw_slots = [
                            int(member.get("slot", 0))
                            for member in merged_party
                            if int(member.get("slot", 0)) > 0
                        ]
                        best_base = min(int(best_base), int(partner_base))
                        best_start_addr = hex(int(best_base))
                        best_stride = int(slot_size)
                        interleaved_recovery_meta = {
                            "original_base": hex(original_base),
                            "companion_base": hex(int(partner_base)),
                            "original_stride": int(original_stride),
                            "selected_stride": int(best_stride),
                            "merged": len(best_party),
                            "expected": int(best_expected_count),
                            "partner_slots": partner_raw_slots,
                        }

                if interleaved_recovery_meta is None:
                    interleaved_recovery_miss_meta = {
                        "base": hex(int(best_base)),
                        "stride": int(best_stride),
                        "decoded": len(best_party),
                        "expected": int(best_expected_count),
                        "probes": interleaved_probe_results,
                    }

            selection = {
                "count_addr": str(best_count_addr),
                "start_addr": str(best_start_addr),
                "base": int(best_base),
                "stride": int(best_stride),
            }
            previous_selection = self._last_gen3_party_selection.get(game_name)
            selection_changed = previous_selection != selection
            self._last_gen3_party_selection[game_name] = selection

            if selection_changed and interleaved_recovery_meta:
                log_event(
                    logging.INFO,
                    "gen3_party_interleaved_recovered",
                    game=game_name,
                    **interleaved_recovery_meta,
                )

            if selection_changed and interleaved_recovery_miss_meta:
                log_event(
                    logging.INFO,
                    "gen3_party_interleaved_unrecovered",
                    game=game_name,
                    **interleaved_recovery_miss_meta,
                )

            if best_expected_count == 0 and best_party and selection_changed:
                log_event(
                    logging.INFO,
                    "gen3_party_count_fallback",
                    game=game_name,
                    count_addr=best_count_addr,
                    decoded=len(best_party),
                )

            if selection_changed and (best_start_addr != primary_start_addr or best_base != int(best_start_addr, 16) or best_count_addr != primary_count_addr):
                log_event(
                    logging.INFO,
                    "gen3_party_base_adjusted",
                    game=game_name,
                    original=primary_start_addr,
                    selected=hex(best_base),
                    decoded=len(best_party),
                    expected=best_expected_count,
                    count_addr=best_count_addr,
                    start_addr=best_start_addr,
                )

            if selection_changed and int(best_stride) != int(slot_size):
                log_event(
                    logging.INFO,
                    "gen3_party_stride_adjusted",
                    game=game_name,
                    selected_stride=best_stride,
                    default_stride=int(slot_size),
                    start_addr=best_start_addr,
                )

            if selection_changed and best_raw_party_len > len(best_party):
                log_event(
                    logging.INFO,
                    "gen3_party_sparse_filtered",
                    game=game_name,
                    decoded=best_raw_party_len,
                    kept=len(best_party),
                    slots=best_raw_slots,
                )

            expected_count_value = int(best_expected_count) if isinstance(best_expected_count, int) and int(best_expected_count) >= 0 else None
            self._last_party_read_meta.update({
                "expected_count": expected_count_value,
                "decoded_count": len(best_party),
                "incomplete": bool(expected_count_value and len(best_party) < expected_count_value),
                "count_addr": str(best_count_addr),
                "start_addr": str(best_start_addr),
                "stride": int(best_stride),
                "budget_hit": bool(budget_exceeded),
                "reason": None,
            })
            metadata_slots = sum(
                1
                for member in best_party
                if isinstance(member, dict) and (
                    (isinstance(member.get("gender"), str) and member.get("gender"))
                    or (isinstance(member.get("nature"), str) and member.get("nature"))
                    or (isinstance(member.get("ability"), str) and member.get("ability"))
                    or (isinstance(member.get("moves"), list) and len(member.get("moves")) > 0)
                )
            )
            if best_party and metadata_slots == 0:
                log_event(
                    logging.WARNING,
                    "gen3_party_metadata_missing",
                    game=game_name,
                    decoded=len(best_party),
                    expected=expected_count_value,
                    start_addr=str(best_start_addr),
                    stride=int(best_stride),
                )
            return best_party

        if not count_valid:
            self._last_party_read_meta.update({
                "expected_count": None,
                "decoded_count": 0,
                "incomplete": False,
                "count_addr": str(party_count_addr),
                "start_addr": str(party_start_addr),
                "stride": int(slot_size),
                "budget_hit": False,
                "reason": "invalid_party_count",
            })
            return []

        # Gen 1/2: species is first byte of slot structure.
        for i in range(int(count)):
            slot_addr_int = int(party_start_addr, 16) + (i * slot_size)
            slot_addr = hex(slot_addr_int)

            species_id = self.retroarch.read_memory(slot_addr)
            slot_data = self.retroarch.read_memory(slot_addr, slot_size)

            level = None
            is_shiny = False
            moves: List[str] = []

            if isinstance(slot_data, list) and len(slot_data) >= slot_size:
                if all(isinstance(v, int) and 0 <= int(v) <= 0xFF for v in slot_data[:slot_size]):
                    slot_bytes = [int(v) & 0xFF for v in slot_data[:slot_size]]
                    species_id = int(slot_bytes[0])
                    if int(gen) == 1:
                        species_id = self._resolve_gen1_species_id(species_id)

                    if int(gen) == 2:
                        # GSC party struct: MON_LEVEL at 0x1F, MON_DVS at 0x15-0x16.
                        for move_offset in (0x02, 0x03, 0x04, 0x05):
                            if len(slot_bytes) > move_offset:
                                rendered = self._resolve_legacy_move_name(slot_bytes[move_offset])
                                if rendered != "-":
                                    moves.append(rendered)
                        if len(slot_bytes) > 0x1F:
                            level_candidate = int(slot_bytes[0x1F])
                            if level_candidate > 0:
                                level = level_candidate
                        if len(slot_bytes) > 0x16:
                            is_shiny = self._is_gen2_shiny_from_dvs(slot_bytes[0x15], slot_bytes[0x16])
                    else:
                        for move_offset in (8, 9, 10, 11):
                            if len(slot_bytes) > move_offset:
                                rendered = self._resolve_legacy_move_name(slot_bytes[move_offset])
                                if rendered != "-":
                                    moves.append(rendered)
                        level_candidate = int(slot_bytes[3]) if len(slot_bytes) > 3 else 0
                        if level_candidate > 0:
                            level = level_candidate

            if species_id is None:
                continue

            try:
                species_id = int(species_id)
            except (TypeError, ValueError):
                continue

            if int(gen) == 1:
                # Gen 1 party species list bytes are also internal IDs on most cores.
                species_list_addr = hex(int(party_count_addr, 16) + 1 + i)
                species_list_value = self.retroarch.read_memory(species_list_addr)
                if isinstance(species_list_value, int):
                    species_list_id = self._resolve_gen1_species_id(species_list_value)
                    max_species = int(config.get("max_pokemon", 151) or 151)
                    if 1 <= species_list_id <= max_species:
                        species_id = species_list_id

            if species_id <= 0:
                continue

            if level is None:
                level_offset = 3
                level_addr = hex(slot_addr_int + level_offset)
                level_value = self.retroarch.read_memory(level_addr)
                if isinstance(level_value, int) and int(level_value) > 0:
                    level = int(level_value)

            member: Dict[str, object] = {
                "id": int(species_id),
                "level": int(level) if isinstance(level, int) and level > 0 else None,
                "slot": i + 1,
            }
            if int(gen) >= 2:
                member["shiny"] = bool(is_shiny)
            if moves:
                member["moves"] = moves[:4]

            party.append(member)

        expected_count_value = int(count) if isinstance(count, int) and int(count) >= 0 else None
        self._last_party_read_meta.update({
            "expected_count": expected_count_value,
            "decoded_count": len(party),
            "incomplete": bool(expected_count_value and len(party) < expected_count_value),
            "count_addr": str(party_count_addr),
            "start_addr": str(party_start_addr),
            "stride": int(slot_size),
            "budget_hit": False,
            "reason": None,
        })
        return party

    def read_wild_encounter(self, game_name: str) -> Optional[Dict[str, object]]:
        """Read current enemy lead encounter when battle party memory is available."""

        def _set_meta(reason: str, **extra):
            payload: Dict[str, object] = {"game": game_name, "reason": str(reason)}
            payload.update(extra)
            self._last_wild_read_meta = payload

        def _parse_hex_addr(value: object) -> Optional[int]:
            try:
                return int(str(value), 16)
            except (TypeError, ValueError):
                return None

        def _dedupe_ints(values: List[int]) -> List[int]:
            seen: Set[int] = set()
            ordered: List[int] = []
            for value in values:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    continue
                if parsed in seen:
                    continue
                seen.add(parsed)
                ordered.append(parsed)
            return ordered

        def _as_hex_list(values: List[int]) -> List[str]:
            rendered: List[str] = []
            for value in values:
                try:
                    rendered.append(hex(int(value)))
                except (TypeError, ValueError):
                    continue
            return rendered

        _set_meta("start")
        config = self.get_game_config(game_name)
        if not config:
            _set_meta("missing_game_config")
            return None

        try:
            gen = int(config.get("gen", 1))
        except (TypeError, ValueError):
            gen = 1
        if gen != 3:
            _set_meta("unsupported_generation", gen=gen)
            return None

        party_count_addr = config.get("party_count")
        party_start_addr = config.get("party_start")
        try:
            slot_size = int(config.get("party_slot_size", 100) or 100)
        except (TypeError, ValueError):
            slot_size = 100

        if not party_count_addr or not party_start_addr or slot_size <= 0:
            _set_meta("missing_party_addresses", slot_size=slot_size)
            return None

        if (
            bool(config.get("party_use_pointer_layout", 0))
            and config.get("saveblock1_ptr")
            and config.get("party_count_offset") is not None
            and config.get("party_start_offset") is not None
        ):
            saveblock1_ptr = self._resolve_gen3_saveblock_ptr(config.get("saveblock1_ptr"), game_name=game_name)
            if saveblock1_ptr is not None:
                party_count_addr = hex(saveblock1_ptr + int(config.get("party_count_offset")))
                party_start_addr = hex(saveblock1_ptr + int(config.get("party_start_offset")))
            elif not bool(config.get("party_allow_static_when_pointer_missing", 1)):
                _set_meta("pointer_layout_unavailable")
                return None

        player_count_candidates: List[int] = []
        player_start_candidates: List[int] = []

        parsed_count_addr = _parse_hex_addr(party_count_addr)
        parsed_start_addr = _parse_hex_addr(party_start_addr)
        if parsed_count_addr is not None:
            player_count_candidates.append(parsed_count_addr)
        if parsed_start_addr is not None:
            player_start_candidates.append(parsed_start_addr)

        raw_count_candidates = config.get("party_count_candidates")
        if isinstance(raw_count_candidates, list):
            for candidate in raw_count_candidates:
                parsed = _parse_hex_addr(candidate)
                if parsed is not None:
                    player_count_candidates.append(parsed)

        raw_start_candidates = config.get("party_start_candidates")
        if isinstance(raw_start_candidates, list):
            for candidate in raw_start_candidates:
                parsed = _parse_hex_addr(candidate)
                if parsed is not None:
                    player_start_candidates.append(parsed)

        meta = self._last_party_read_meta if isinstance(self._last_party_read_meta, dict) else {}
        meta_count_addr = _parse_hex_addr(meta.get("count_addr"))
        meta_start_addr = _parse_hex_addr(meta.get("start_addr"))
        if meta_count_addr is not None:
            player_count_candidates.append(meta_count_addr)
        if meta_start_addr is not None:
            player_start_candidates.append(meta_start_addr)

        player_count_candidates = _dedupe_ints(player_count_candidates)
        player_start_candidates = _dedupe_ints(player_start_candidates)
        if not player_count_candidates or not player_start_candidates:
            _set_meta(
                "missing_player_candidates",
                player_count_candidates=_as_hex_list(player_count_candidates),
                player_start_candidates=_as_hex_list(player_start_candidates),
            )
            return None

        enemy_count_reads: List[Tuple[int, int, int, int]] = []
        count_addr_candidates: List[int] = []
        for base_count_addr in player_count_candidates:
            for offset in (1, 2, 3):
                count_addr_candidates.append(int(base_count_addr + offset))
        configured_enemy_count_addr = _parse_hex_addr(config.get("enemy_party_count"))
        if configured_enemy_count_addr is not None:
            count_addr_candidates.append(configured_enemy_count_addr)

        count_addr_candidates = _dedupe_ints(count_addr_candidates)
        for addr_idx, count_addr_int in enumerate(count_addr_candidates):
            count_value = self.retroarch.read_memory(hex(count_addr_int))
            if not isinstance(count_value, int):
                continue
            parsed_count = int(count_value)
            if 1 <= parsed_count <= 6:
                wild_rank = 0 if parsed_count == 1 else 1
                enemy_count_reads.append((wild_rank, int(addr_idx), parsed_count, int(count_addr_int)))

        enemy_count = 0
        enemy_count_addr: Optional[int] = None
        enemy_count_source = "unavailable"
        if enemy_count_reads:
            enemy_count_reads.sort(key=lambda item: (item[0], item[1], item[2]))
            enemy_count = int(enemy_count_reads[0][2])
            enemy_count_addr = int(enemy_count_reads[0][3])
            enemy_count_source = "count_addr"

        enemy_start_candidates: List[int] = []
        for player_start_addr_int in player_start_candidates:
            enemy_start_candidates.append(int(player_start_addr_int + (slot_size * 6)))
        configured_enemy_start_addr = _parse_hex_addr(config.get("enemy_party_start"))
        if configured_enemy_start_addr is not None:
            enemy_start_candidates.append(configured_enemy_start_addr)
        raw_enemy_start_candidates = config.get("enemy_party_start_candidates")
        if isinstance(raw_enemy_start_candidates, list):
            for candidate in raw_enemy_start_candidates:
                parsed = _parse_hex_addr(candidate)
                if parsed is not None:
                    enemy_start_candidates.append(parsed)

        enemy_start_candidates = _dedupe_ints(enemy_start_candidates)
        if not enemy_start_candidates:
            _set_meta(
                "missing_enemy_start_candidates",
                player_start_candidates=_as_hex_list(player_start_candidates),
                enemy_count_source=enemy_count_source,
            )
            return None

        details: Optional[Dict[str, object]] = None
        selected_enemy_start: Optional[int] = None
        decode_attempts = 0
        for enemy_start_addr_int in enemy_start_candidates:
            slot_bytes = self._read_gen3_slot_bytes_for_details(enemy_start_addr_int, int(slot_size))
            if not isinstance(slot_bytes, list) or len(slot_bytes) < int(slot_size):
                continue

            decode_attempts += 1
            decoded = self._decode_gen3_party_slot_details(
                slot_bytes,
                max_species_id=int(self.GEN3_INTERNAL_SPECIES_MAX),
                allow_checksum_mismatch=True,
                species_hint_ids=None,
            )
            if not isinstance(decoded, dict):
                continue

            try:
                decoded_species = int(decoded.get("normalized_species", 0))
            except (TypeError, ValueError):
                decoded_species = 0
            if decoded_species <= 0:
                continue

            details = decoded
            selected_enemy_start = int(enemy_start_addr_int)
            break

        if not isinstance(details, dict):
            _set_meta(
                "enemy_decode_failed",
                player_count_candidates=_as_hex_list(player_count_candidates),
                player_start_candidates=_as_hex_list(player_start_candidates),
                enemy_count_addr=hex(enemy_count_addr) if enemy_count_addr is not None else None,
                enemy_count=enemy_count,
                enemy_count_source=enemy_count_source,
                enemy_start_candidates=_as_hex_list(enemy_start_candidates),
                decode_attempts=int(decode_attempts),
            )
            return None

        try:
            species_id = int(details.get("normalized_species", 0))
        except (TypeError, ValueError):
            species_id = 0
        if species_id <= 0:
            _set_meta(
                "invalid_species",
                enemy_start=hex(selected_enemy_start) if selected_enemy_start is not None else None,
            )
            return None

        try:
            level_val = int(details.get("level", 0))
        except (TypeError, ValueError):
            level_val = 0

        personality = details.get("_personality")
        ot_id = details.get("_ot_id")
        signature = f"{species_id}:{level_val}:{personality}:{ot_id}"
        is_wild = bool(enemy_count == 1) if enemy_count > 0 else True

        _set_meta(
            "ok",
            species_id=int(species_id),
            level=int(level_val) if int(level_val) > 0 else None,
            enemy_count=int(enemy_count) if enemy_count > 0 else None,
            enemy_count_source=enemy_count_source,
            enemy_count_addr=hex(enemy_count_addr) if enemy_count_addr is not None else None,
            enemy_start=hex(selected_enemy_start) if selected_enemy_start is not None else None,
            is_wild=bool(is_wild),
        )

        return {
            "species_id": int(species_id),
            "species_name": self.get_pokemon_name(int(species_id)),
            "level": int(level_val) if int(level_val) > 0 else None,
            "shiny": bool(details.get("shiny", False)),
            "personality": int(personality) if isinstance(personality, int) else personality,
            "ot_id": int(ot_id) if isinstance(ot_id, int) else ot_id,
            "enemy_count": int(enemy_count) if int(enemy_count) > 0 else 0,
            "is_wild": bool(is_wild),
            "signature": signature,
        }
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
        self._collection_baseline_candidate: List[int] = []
        self._collection_baseline_candidate_streak = 0
        self._unlock_streaks: Dict[str, int] = {}
        self._bad_read_streak = 0
        self._achievement_poll_count = 0
        self._collection_wait_streak = 0
        self._empty_pokedex_streak = 0
        self._poll_heartbeat_count = 0
        self._poll_disconnected_streak = 0
        self._party_skip_streak = 0
        self._pending_party_change: Optional[Dict[str, object]] = None
        self._baseline_snapshot_pending = False
        self._baseline_snapshot_wait_polls = 0
        self._cached_pokedex_for_poll: Optional[List[int]] = None
        self._warmup_logged = False
        self._startup_baseline_captured = False
        self._startup_lockout_ids: set[str] = set()
        self._last_bad_read_reconnect_at = 0.0
        self._bad_read_reconnect_cooldown_s = 30.0
        self.validation_profiles: Dict[str, object] = {}
        self.recent_anomalies: List[Dict] = []
        self._derived_checker: Optional[DerivedAchievementChecker] = None
        self._warning_last_log: Dict[str, float] = {}
    
    def set_validation_profiles(self, profiles: Dict[str, object]):
        """Inject validation profile config loaded from JSON."""
        self.validation_profiles = profiles or {}

    def _record_anomaly(self, kind: str, **fields):
        entry = {"time": datetime.now().isoformat(), "kind": kind, **fields}
        self.recent_anomalies.append(entry)
        if len(self.recent_anomalies) > 100:
            self.recent_anomalies = self.recent_anomalies[-100:]

    def _log_warning_throttled(self, kind: str, cooldown_s: float = 10.0, throttle_key: Optional[str] = None, **fields) -> bool:
        """Emit warning logs with a per-key cooldown to reduce repeated chatter."""
        key = throttle_key or kind
        now = time.monotonic()
        last = float(self._warning_last_log.get(key, 0.0))
        if cooldown_s > 0 and (now - last) < float(cooldown_s):
            return False
        self._warning_last_log[key] = now
        log_event(logging.WARNING, kind, **fields)
        return True

    def _get_validation_profile(self) -> Dict[str, int]:
        """Per-game validation thresholds loaded from JSON config."""
        gen = 1
        if self.game_name and self.pokemon_reader:
            cfg = self.pokemon_reader.get_game_config(self.game_name)
            if cfg:
                gen = int(cfg.get("gen", 1))

        config = self.validation_profiles if isinstance(self.validation_profiles, dict) else {}
        default_by_gen = config.get("default_by_gen", {}) if isinstance(config.get("default_by_gen", {}), dict) else {}
        fallback_defaults = {
            "max_unlocks_per_poll": 3,
            "max_new_catches_per_poll": 5,
            "max_major_unlocks_per_poll": 2,
            "max_legendary_unlocks_per_poll": 1,
            "unlock_warmup_polls": 4,
            "unlock_confirmations_default": 2,
            "unlock_confirmations_legendary": 3,
            "unlock_confirmations_gym_gen3": 2,
            "collection_baseline_confirmations": 2,
            "collection_empty_baseline_wait_polls": 10,
            "collection_first_nonempty_confirmations": 2,
            "collection_empty_drop_confirmations": 3,
            "startup_lockout_enabled": 0,
            "startup_snapshot_window_polls": 30,
            "startup_max_unlocks_per_poll": 12,
            "startup_max_major_unlocks_per_poll": 10,
            "startup_unlock_confirmations_default": 1,
            "startup_unlock_confirmations_legendary": 2,
            "startup_unlock_confirmations_gym_gen3": 1,
        }

        raw_default = default_by_gen.get(str(gen), {})
        profile = dict(fallback_defaults)
        if isinstance(raw_default, dict):
            profile.update({k: int(v) for k, v in raw_default.items() if isinstance(v, (int, float))})

        per_game = config.get("per_game", {}) if isinstance(config.get("per_game", {}), dict) else {}
        if self.game_name:
            key = self.game_name.lower().replace(" ", "_").replace("'", "")
            override = per_game.get(key)
            if isinstance(override, dict):
                profile.update({k: int(v) for k, v in override.items() if isinstance(v, (int, float))})

        return {k: int(v) for k, v in profile.items() if isinstance(v, (int, float))}

    def _handle_bad_read(self, reason: str):
        """Track repeated suspicious reads and attempt lightweight auto-recovery."""
        if bool(getattr(self.retroarch, "is_waiting_for_launch", lambda: False)()):
            self._bad_read_streak = 0
            return
        self._bad_read_streak += 1
        self._record_anomaly("memory_read_suspicious", game=self.game_name, reason=reason, streak=self._bad_read_streak)
        self._log_warning_throttled("memory_read_suspicious", cooldown_s=5.0, throttle_key=f"memory_read_suspicious:{self.game_name}:{reason}", game=self.game_name, reason=reason, streak=self._bad_read_streak)
        if self._bad_read_streak >= 3:
            now = time.monotonic()
            reconnect_cooldown = max(5.0, float(getattr(self, "_bad_read_reconnect_cooldown_s", 30.0)))
            last_reconnect = float(getattr(self, "_last_bad_read_reconnect_at", 0.0))
            if (now - last_reconnect) < reconnect_cooldown:
                self._bad_read_streak = 2
                return
            self._last_bad_read_reconnect_at = now
            self._record_anomaly("memory_read_reconnect", game=self.game_name)
            self._log_warning_throttled("memory_read_reconnect", cooldown_s=5.0, throttle_key=f"memory_read_reconnect:{self.game_name}", game=self.game_name)
            self.retroarch.disconnect()
            self.retroarch.connect()
            self._bad_read_streak = 0

    def _current_generation(self) -> int:
        if self.game_name and self.pokemon_reader:
            cfg = self.pokemon_reader.get_game_config(self.game_name)
            if cfg:
                return int(cfg.get("gen", 1))
        return 1

    def _is_plausible_badge_byte(self, badge_byte: int, generation: Optional[int] = None) -> bool:
        """Badge byte sanity check. Gen 3 does not follow strict contiguous progression bits."""
        gen = generation if generation is not None else self._current_generation()
        try:
            byte_value = int(badge_byte)
        except (TypeError, ValueError):
            return False

        if gen >= 3:
            return 0 <= byte_value <= 0xFF

        plausible = {0, 1, 3, 7, 15, 31, 63, 127, 255}
        return byte_value in plausible

    def _gen3_contiguous_badge_count(self, badge_byte: int) -> int:
        """Return count of badges in strict progression order (1->8)."""
        count = 0
        value = int(badge_byte)
        for bit in range(8):
            if value & (1 << bit):
                count += 1
            else:
                break
        return count

    def _read_gen3_gym_progress_count(self) -> Optional[int]:
        """Read contiguous Gen 3 gym progression count using save flags when available."""
        if self._current_generation() != 3 or not self.game_name or not self.pokemon_reader:
            return None

        config = self.pokemon_reader.get_game_config(self.game_name)
        if not config:
            return None

        progression_flags = config.get("gym_progression_flags")
        if isinstance(progression_flags, list) and progression_flags:
            states: List[bool] = []
            for flag_id in progression_flags:
                state = self.pokemon_reader.read_gen3_event_flag(self.game_name, int(flag_id))
                if state is None:
                    states = []
                    break
                states.append(bool(state))

            if states:
                count = 0
                for state in states:
                    if state:
                        count += 1
                    else:
                        break
                return count

        badge_addr = config.get("badge_address")
        badge_byte = self.retroarch.read_memory(badge_addr) if badge_addr else None
        if isinstance(badge_byte, int) and self._is_plausible_badge_byte(badge_byte, generation=3):
            return self._gen3_contiguous_badge_count(badge_byte)

        return None

    def _required_unlock_confirmations(self, achievement: Achievement, profile: Dict[str, int], startup_window: bool = False) -> int:
        """Return confirmation streak requirement for an unlock candidate."""
        default_key = "startup_unlock_confirmations_default" if startup_window else "unlock_confirmations_default"
        legendary_key = "startup_unlock_confirmations_legendary" if startup_window else "unlock_confirmations_legendary"
        gym_key = "startup_unlock_confirmations_gym_gen3" if startup_window else "unlock_confirmations_gym_gen3"

        required = max(1, int(profile.get(default_key, profile.get("unlock_confirmations_default", 2))))

        if achievement.category == "legendary":
            required = max(required, int(profile.get(legendary_key, profile.get("unlock_confirmations_legendary", 3))))

        if achievement.category == "gym" and self._current_generation() == 3:
            required = max(required, int(profile.get(gym_key, profile.get("unlock_confirmations_gym_gen3", 2))))

        return required

    def _safe_gen3_story_check(self, achievement: Achievement) -> Optional[bool]:
        """Extra guardrails for noisy Gen 3 story-memory reads."""
        if self._current_generation() != 3 or not self.game_name:
            return None

        if achievement.category not in {"gym", "elite_four", "champion"}:
            return None

        config = self.pokemon_reader.get_game_config(self.game_name) if self.pokemon_reader else None
        if not config:
            return None

        badge_addr = config.get("badge_address")
        if not badge_addr:
            return None

        badge_byte = self.retroarch.read_memory(badge_addr)
        if badge_byte is None:
            return False

        if not self._is_plausible_badge_byte(badge_byte, generation=3):
            self._record_anomaly("badge_state_implausible", game=self.game_name, badge_byte=badge_byte)
            log_event(logging.WARNING, "badge_state_implausible", game=self.game_name, badge_byte=badge_byte)
            return False

        if achievement.category == "gym":
            # Gen 3 gym progression is linear; gate unlocks by contiguous badge progression
            # so noisy/non-contiguous badge bytes do not unlock wrong badges.
            condition = (achievement.memory_condition or "").strip().lower()
            if condition.startswith("&"):
                try:
                    mask_text = condition[1:].strip()
                    mask_value = int(mask_text, 16) if "x" in mask_text else int(mask_text)
                except ValueError:
                    mask_value = 0

                if mask_value > 0 and (mask_value & (mask_value - 1)) == 0:
                    required_badges = int(mask_value).bit_length()
                    contiguous_count = self._gen3_contiguous_badge_count(badge_byte)
                    if self.evaluate_condition(badge_byte, achievement.memory_condition) and contiguous_count < required_badges:
                        self._record_anomaly(
                            "badge_state_noncontiguous",
                            game=self.game_name,
                            badge_byte=int(badge_byte),
                            contiguous_count=contiguous_count,
                            required_badges=required_badges,
                        )
                        log_event(
                            logging.WARNING,
                            "badge_state_noncontiguous",
                            game=self.game_name,
                            badge_byte=int(badge_byte),
                            contiguous_count=contiguous_count,
                            required_badges=required_badges,
                        )
                    return contiguous_count >= required_badges

            return self.evaluate_condition(badge_byte, achievement.memory_condition)

        # Elite Four/Champion should not unlock without all badges.
        if badge_byte != 0xFF:
            return False

        # Fall back to raw memory flag once badge precondition is met.
        value = self.retroarch.read_memory(achievement.memory_address)
        if value is None:
            return False
        return self.evaluate_condition(value, achievement.memory_condition)

    def _should_use_derived_check(self, achievement: Achievement) -> bool:
        """Select derived checks for categories/IDs that are safer than raw address checks."""
        ach_id = achievement.id.lower()
        if achievement.category in {"pokedex", "legendary"}:
            return True
        if achievement.category == "gym" and self._current_generation() == 3:
            return True
        if ach_id.endswith("_gym_all") or ach_id.endswith("_elite_four_all") or ach_id.endswith("_pokemon_master"):
            return True
        if any(token in ach_id for token in ("first_steps", "starter_chosen", "journey_begins")) or "_story_hm_" in ach_id:
            return True
        return not (achievement.memory_address and achievement.memory_condition)

    def _read_pokedex_count_hint(self) -> Optional[int]:
        """Read a count hint from dedicated count memory when trustworthy."""
        if not self.game_name:
            return None

        config = self.pokemon_reader.get_game_config(self.game_name) if self.pokemon_reader else None
        if not config:
            return None

        gen = int(config.get("gen", 1))
        max_pokemon = int(config.get("max_pokemon") or (151 if gen == 1 else (251 if gen == 2 else 386)))

        # Prefer explicit per-game count address when available.
        count_addr = config.get("pokedex_count")
        if count_addr:
            value = self.retroarch.read_memory(count_addr)
            if isinstance(value, int) and 0 <= value <= max_pokemon:
                return int(value)

        # Gen 3 achievement memory fields are often seen-count/proxy values,
        # so avoid inferring caught-count hints from them.
        if gen >= 3:
            return None

        candidates = [
            ach for ach in self.achievements
            if ach.category == "pokedex" and ach.memory_address and ach.memory_condition.startswith(">=")
        ]
        candidates.sort(key=lambda ach: int(ach.target_value or 0))

        for ach in candidates:
            value = self.retroarch.read_memory(ach.memory_address)
            if isinstance(value, int) and 0 <= value <= max_pokemon:
                return int(value)

        return None

    def _read_current_pokedex_caught(self) -> List[int]:
        """Read current caught list with count-hint sanity guard and per-poll caching."""
        if not self.game_name or not self.pokemon_reader:
            return []

        if isinstance(self._cached_pokedex_for_poll, list):
            return list(self._cached_pokedex_for_poll)

        count_hint = self._read_pokedex_count_hint()
        current = self.pokemon_reader.read_pokedex(self.game_name, count_hint=count_hint)

        if count_hint is None:
            self._cached_pokedex_for_poll = list(current)
            return current

        tolerance = max(5, int(count_hint) // 2)
        if abs(len(current) - int(count_hint)) > tolerance:
            self._record_anomaly(
                "pokedex_count_mismatch",
                game=self.game_name,
                count_hint=count_hint,
                bitset_count=len(current),
                tolerance=tolerance,
            )
            log_event(
                logging.WARNING,
                "pokedex_count_mismatch",
                game=self.game_name,
                count_hint=count_hint,
                bitset_count=len(current),
                tolerance=tolerance,
            )
            if self._last_pokedex:
                cached = list(self._last_pokedex)
                self._cached_pokedex_for_poll = cached
                return cached

        self._cached_pokedex_for_poll = list(current)
        return current

    def _read_current_party(self) -> List[Dict]:
        """Read current party without letting party decode errors stall other trackers."""
        if not self.game_name or not self.pokemon_reader:
            return []

        try:
            party_hint = self._cached_pokedex_for_poll if isinstance(self._cached_pokedex_for_poll, list) else self._last_pokedex
            try:
                party = self.pokemon_reader.read_party(self.game_name, caught_ids_hint=party_hint)
            except TypeError:
                party = self.pokemon_reader.read_party(self.game_name)
        except Exception as exc:
            self._record_anomaly(
                "party_read_exception",
                game=self.game_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            log_event(
                logging.WARNING,
                "party_read_exception",
                game=self.game_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return list(self._last_party)

        if not isinstance(party, list):
            self._record_anomaly(
                "party_read_invalid",
                game=self.game_name,
                reason="non_list",
                value_type=type(party).__name__,
            )
            log_event(
                logging.WARNING,
                "party_read_invalid",
                game=self.game_name,
                reason="non_list",
                value_type=type(party).__name__,
            )
            return list(self._last_party)

        normalized_party: List[Dict] = []
        for member in party:
            if not isinstance(member, dict):
                continue
            try:
                pokemon_id = int(member.get("id", 0))
                slot = int(member.get("slot", 0))
            except (TypeError, ValueError):
                continue
            if pokemon_id <= 0 or slot < 1 or slot > 6:
                continue

            level: Optional[int] = None
            raw_level = member.get("level")
            if isinstance(raw_level, (int, float)):
                level_candidate = int(raw_level)
                if 1 <= level_candidate <= 100:
                    level = level_candidate

            normalized_member: Dict[str, object] = {
                "id": pokemon_id,
                "level": level,
                "slot": slot,
            }
            if bool(member.get("shiny", False)):
                normalized_member["shiny"] = True
            raw_name = member.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                normalized_member["name"] = raw_name.strip()

            for key in ("gender", "nature", "ability"):
                value = member.get(key)
                if isinstance(value, str) and value.strip():
                    normalized_member[key] = value.strip()

            raw_moves = member.get("moves")
            if isinstance(raw_moves, list):
                clean_moves = [
                    str(move).strip()
                    for move in raw_moves
                    if isinstance(move, str) and str(move).strip()
                ]
                if clean_moves:
                    normalized_member["moves"] = clean_moves[:4]

            # Preserve Gen3 shiny debug metadata for structured party_slot logging.
            for src_key, dst_key in (("_shiny_xor", "_shiny_xor"), ("shiny_xor", "_shiny_xor"), ("_personality", "_personality"), ("personality", "_personality"), ("_ot_id", "_ot_id"), ("ot_id", "_ot_id")):
                raw_value = member.get(src_key)
                if raw_value is None:
                    continue
                try:
                    normalized_member[dst_key] = int(raw_value)
                except (TypeError, ValueError):
                    continue

            normalized_party.append(normalized_member)

        if party and not normalized_party:
            self._record_anomaly("party_read_invalid", game=self.game_name, reason="no_valid_slots")
            log_event(logging.WARNING, "party_read_invalid", game=self.game_name, reason="no_valid_slots")
            return list(self._last_party)

        normalized_party.sort(key=lambda member: int(member.get("slot", 0)))
        return normalized_party

    def load_game(self, game_name: str, achievements_file: Path) -> bool:
        """Load achievements for a specific game"""
        try:
            with open(achievements_file, 'r') as f:
                data = json.load(f)
            
            self.achievements = []
            for ach_data in data.get("achievements", []):
                self.achievements.append(Achievement(
                    id=ach_data["id"],
                    name=str(ach_data.get("name", "")).strip(),
                    description=ach_data["description"],
                    category=ach_data.get("category", "misc"),
                    rarity=ach_data.get("rarity", "common"),
                    points=ach_data.get("points", 10),
                    memory_address=ach_data.get("memory_address", ""),
                    memory_condition=ach_data.get("memory_condition", ""),
                    target_value=ach_data.get("target_value"),
                ))
            
            self.game_name = game_name
            self.game_id = self.GAME_IDS.get(game_name)
            self._last_party = []
            self._last_pokedex = []
            self._collection_baseline_initialized = False
            self._collection_baseline_candidate = []
            self._collection_baseline_candidate_streak = 0
            self._unlock_streaks = {}
            self._bad_read_streak = 0
            self._achievement_poll_count = 0
            self._collection_wait_streak = 0
            self._empty_pokedex_streak = 0
            self._poll_heartbeat_count = 0
            self._poll_disconnected_streak = 0
            self._party_skip_streak = 0
            self._pending_party_change = None
            self._baseline_snapshot_pending = False
            self._baseline_snapshot_wait_polls = 0
            self._cached_pokedex_for_poll = None
            self._warmup_logged = False
            self._startup_baseline_captured = False
            self._startup_lockout_ids = set()

            validation = self.pokemon_reader.validate_memory_profile(game_name)
            log_event(logging.INFO, "memory_profile_validation", game=game_name, ok=validation.get("ok"), failures=validation.get("failures", []), warnings=validation.get("warnings", []))

            # Initialize derived achievement checker
            if GAME_CONFIGS_AVAILABLE and self.game_name:
                try:
                    self._derived_checker = DerivedAchievementChecker(self.retroarch, self.game_name)
                except ValueError:
                    self._derived_checker = None
            
            return True
        except Exception as e:
            return False
    
    def reconcile_local_unlocks(self) -> int:
        """Reconcile obviously invalid local unlocks against stable in-game state."""
        corrected = 0

        if self._current_generation() == 3:
            badge_count = self._read_gen3_gym_progress_count()
            if badge_count is not None:
                for ach in self.achievements:
                    ach_id = ach.id.lower()
                    if ach_id.endswith("_gym_all") and ach.unlocked and badge_count < 8:
                        ach.unlocked = False
                        ach.unlocked_at = None
                        corrected += 1
                        continue
                    gym_match = re.search(r"_gym_(\d+)$", ach_id)
                    if ach.category == "gym" and gym_match and ach.unlocked:
                        try:
                            required = int(gym_match.group(1))
                        except (TypeError, ValueError):
                            continue
                        if required > badge_count:
                            ach.unlocked = False
                            ach.unlocked_at = None
                            corrected += 1

        if corrected:
            log_event(logging.INFO, "local_unlocks_reconciled", game=self.game_name, corrected=corrected)

        return corrected

    def load_progress(self, progress_file: Path):
        """Load previously unlocked achievements"""
        if not progress_file.exists():
            return

        try:
            with open(progress_file, 'r') as f:
                data = json.load(f)

            unlocked_ids = set(data.get("unlocked", []))
            loaded_count = 0
            for ach in self.achievements:
                if ach.id in unlocked_ids:
                    ach.unlocked = True
                    loaded_count += 1
            log_event(logging.INFO, "progress_load_applied", game=self.game_name, unlocked=loaded_count)
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
        self._achievement_poll_count += 1
        warmup_polls = max(0, int(profile.get("unlock_warmup_polls", 4)))
        if self._achievement_poll_count <= warmup_polls:
            if not self._warmup_logged:
                log_event(logging.INFO, "unlock_warmup_active", game=self.game_name, polls=warmup_polls)
                self._warmup_logged = True
            return []

        startup_lockout_enabled = bool(profile.get("startup_lockout_enabled", 0))
        baseline_mode = (not self._startup_baseline_captured) and startup_lockout_enabled
        if baseline_mode:
            self._startup_lockout_ids = set()
        elif not self._startup_baseline_captured:
            self._startup_baseline_captured = True

        startup_window_polls = max(1, int(profile.get("startup_snapshot_window_polls", 30)))
        max_unlocks_per_poll = int(profile.get("max_unlocks_per_poll", 3))
        max_major_unlocks_per_poll = int(profile.get("max_major_unlocks_per_poll", 2))
        in_startup_window = self._achievement_poll_count <= startup_window_polls
        if in_startup_window:
            startup_unlock_cap = int(profile.get("startup_max_unlocks_per_poll", 12))
            startup_major_cap = int(profile.get("startup_max_major_unlocks_per_poll", 10))
            max_unlocks_per_poll = max(max_unlocks_per_poll, startup_unlock_cap)
            max_major_unlocks_per_poll = max(max_major_unlocks_per_poll, startup_major_cap)

        candidates_this_poll = 0
        major_candidates_this_poll = 0
        legendary_candidates_this_poll = 0

        for achievement in self.achievements:
            if achievement.unlocked:
                continue
            
            unlocked = False
            
            if self._should_use_derived_check(achievement):
                unlocked = self._check_derived_achievement(achievement)
            else:
                # Direct memory check (achievements with memory_address)
                safe_result = self._safe_gen3_story_check(achievement)
                if safe_result is not None:
                    unlocked = safe_result
                else:
                    value = self.retroarch.read_memory(achievement.memory_address)
                    if value is not None and self.evaluate_condition(value, achievement.memory_condition):
                        unlocked = True
            
            if baseline_mode:
                if unlocked:
                    self._startup_lockout_ids.add(achievement.id)
                continue

            if achievement.id in self._startup_lockout_ids:
                if not unlocked:
                    self._startup_lockout_ids.discard(achievement.id)
                continue

            if unlocked:
                candidates_this_poll += 1
                if candidates_this_poll > max_unlocks_per_poll:
                    self._record_anomaly("unlock_spike_ignored", game=self.game_name, candidates=candidates_this_poll, threshold=max_unlocks_per_poll)
                    self._log_warning_throttled("unlock_spike_ignored", cooldown_s=30.0, throttle_key=f"unlock_spike_ignored:{self.game_name}", game=self.game_name, candidates=candidates_this_poll, threshold=max_unlocks_per_poll)
                    self._unlock_streaks[achievement.id] = 0
                    continue

                if achievement.category in {"gym", "elite_four", "champion", "legendary"}:
                    major_candidates_this_poll += 1
                    if major_candidates_this_poll > max_major_unlocks_per_poll:
                        self._record_anomaly("major_unlock_spike_ignored", game=self.game_name, category=achievement.category, count=major_candidates_this_poll, threshold=max_major_unlocks_per_poll)
                        self._log_warning_throttled("major_unlock_spike_ignored", cooldown_s=30.0, throttle_key=f"major_unlock_spike_ignored:{self.game_name}:{achievement.category}", game=self.game_name, category=achievement.category, count=major_candidates_this_poll, threshold=max_major_unlocks_per_poll)
                        self._unlock_streaks[achievement.id] = 0
                        continue

                if achievement.category == "legendary":
                    legendary_candidates_this_poll += 1
                    max_legendary = profile.get("max_legendary_unlocks_per_poll", 1)
                    if legendary_candidates_this_poll > max_legendary:
                        self._record_anomaly("legendary_unlock_spike_ignored", game=self.game_name, count=legendary_candidates_this_poll, threshold=max_legendary)
                        self._log_warning_throttled("legendary_unlock_spike_ignored", cooldown_s=30.0, throttle_key=f"legendary_unlock_spike_ignored:{self.game_name}", game=self.game_name, count=legendary_candidates_this_poll, threshold=max_legendary)
                        self._unlock_streaks[achievement.id] = 0
                        continue

                self._unlock_streaks[achievement.id] = self._unlock_streaks.get(achievement.id, 0) + 1
                required_confirmations = self._required_unlock_confirmations(achievement, profile, startup_window=in_startup_window)
                # Require configurable consecutive positive polls to avoid transient memory-read false positives.
                if self._unlock_streaks[achievement.id] >= required_confirmations:
                    achievement.unlocked = True
                    achievement.unlocked_at = datetime.now().isoformat()
                    newly_unlocked.append(achievement)
                    self._unlock_queue.put(achievement)
                    self.post_unlock_to_platform(achievement)
            else:
                self._unlock_streaks[achievement.id] = 0
        
        if baseline_mode:
            self._startup_baseline_captured = True
            if self._startup_lockout_ids:
                log_event(logging.INFO, "unlock_startup_lockout", game=self.game_name, count=len(self._startup_lockout_ids))
            return []

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
        
        # Pokedex count achievements (including complete) prioritize JSON target values.
        if "pokedex" in ach_id and not ach_id.endswith("_master"):
            current_pokedex = self._read_current_pokedex_caught()
            caught_count = len(current_pokedex)
            if achievement.target_value is not None:
                return caught_count >= int(achievement.target_value)
            if "_pokedex_10" in ach_id:
                return caught_count >= 10
            if "_pokedex_25" in ach_id:
                return caught_count >= 25
            if "_pokedex_50" in ach_id:
                return caught_count >= 50
            if "_pokedex_100" in ach_id:
                return caught_count >= 100
            if "_pokedex_150" in ach_id or "_pokedex_200" in ach_id:
                config = get_game_config(self.game_name) if GAME_CONFIGS_AVAILABLE else None
                max_pokemon = config.max_pokemon if config else 150
                return caught_count >= max_pokemon
            if "_pokedex_151" in ach_id or "_pokedex_251" in ach_id or "_pokedex_386" in ach_id:
                config = get_game_config(self.game_name) if GAME_CONFIGS_AVAILABLE else None
                max_pokemon = config.max_pokemon if config else 151
                return caught_count >= max_pokemon
        # Gen 3 gym achievements rely on save flags for stable progression checks.
        if achievement.category == "gym" and self._current_generation() == 3:
            badge_count = self._read_gen3_gym_progress_count()
            if badge_count is not None:
                if ach_id.endswith("_gym_all"):
                    return badge_count >= 8
                gym_match = re.search(r"_gym_(\d+)$", ach_id)
                if gym_match:
                    try:
                        return badge_count >= int(gym_match.group(1))
                    except (TypeError, ValueError):
                        pass

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
        
        # Legendary achievements derived from current Pokedex set.
        if "legendary" in ach_id:
            current_pokedex = set(self._read_current_pokedex_caught())
            legendary_ids = {
                "articuno": 144,
                "zapdos": 145,
                "moltres": 146,
                "mewtwo": 150,
                "mew": 151,
                "raikou": 243,
                "entei": 244,
                "suicune": 245,
                "lugia": 249,
                "ho-oh": 250,
                "celebi": 251,
                "regirock": 377,
                "regice": 378,
                "registeel": 379,
                "latias": 380,
                "latios": 381,
                "kyogre": 382,
                "groudon": 383,
                "rayquaza": 384,
                "jirachi": 385,
                "deoxys": 386,
            }

            if ach_id.endswith("_legendary_all_weather"):
                return all(x in current_pokedex for x in [382, 383, 384])
            if ach_id.endswith("_legendary_regi_trio"):
                return all(x in current_pokedex for x in [377, 378, 379])
            if ach_id.endswith("_legendary_latias_latios"):
                return all(x in current_pokedex for x in [380, 381])
            if ach_id.endswith("_legendary_birds"):
                return all(x in current_pokedex for x in [144, 145, 146])
            if ach_id.endswith("_legendary_all"):
                gen = self._current_generation()
                if gen == 1:
                    required = [144, 145, 146, 150]
                elif gen == 2:
                    required = [243, 244, 245, 249, 250]
                else:
                    required = [377, 378, 379, 380, 381, 382, 383, 384]
                return all(x in current_pokedex for x in required)

            for legendary, pokemon_id in legendary_ids.items():
                if ach_id.endswith(f"_legendary_{legendary}"):
                    return pokemon_id in current_pokedex
        
        # First steps
        if any(token in ach_id for token in ("first_steps", "starter_chosen", "journey_begins")):
            # Keep first-steps independent from live party decoding; rely on Pokedex/event flags first.
            if self.pokemon_reader and self.game_name:
                if self._read_current_pokedex_caught():
                    return True
                if self._current_generation() == 3:
                    config = self.pokemon_reader.get_game_config(self.game_name)
                    adventure_flag = config.get("adventure_started_flag") if config else None
                    if adventure_flag is not None:
                        started = self.pokemon_reader.read_gen3_event_flag(self.game_name, int(adventure_flag))
                        if started is True:
                            return True
            try:
                return bool(self._derived_checker.check_first_steps())
            except Exception as exc:
                self._record_anomaly(
                    "derived_first_steps_error",
                    game=self.game_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                log_event(
                    logging.WARNING,
                    "derived_first_steps_error",
                    game=self.game_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return False
        
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
            if not self._derived_checker.check_all_badges():
                return False
            if not self._derived_checker.check_champion_defeated():
                return False
            caught_count = len(self._read_current_pokedex_caught())
            return caught_count >= self._get_pokedex_completion_target()
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
        if any(token in ach_id for token in ("first_steps", "starter_chosen", "journey_begins")):
            return self._check_first_steps_legacy()
        
        # Pokemon Master
        if ach_id.endswith("_pokemon_master"):
            return self._check_pokemon_master_legacy()
        
        return False
    
    def _check_pokedex_achievement_legacy(self, achievement: Achievement) -> bool:
        """Legacy pokedex count check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self._read_current_pokedex_caught()
        caught_count = len(current_pokedex)
        if achievement.target_value is not None:
            return caught_count >= int(achievement.target_value)
        
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
        
        current_pokedex = self._read_current_pokedex_caught()
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
        
        current_pokedex = self._read_current_pokedex_caught()
        birds = [144, 145, 146]
        return all(bird in current_pokedex for bird in birds)
    
    def _check_all_legendaries_legacy(self) -> bool:
        """Legacy all legendaries check"""
        if not self.pokemon_reader:
            return False
        
        current_pokedex = self._read_current_pokedex_caught()
        legendaries = [144, 145, 146, 150]
        return all(leg in current_pokedex for leg in legendaries)
    
    def _check_first_steps_legacy(self) -> bool:
        """Legacy first steps check"""
        if not self.pokemon_reader:
            return False

        if self._read_current_pokedex_caught():
            return True

        if self._current_generation() == 3:
            config = self.pokemon_reader.get_game_config(self.game_name)
            adventure_flag = config.get("adventure_started_flag") if config else None
            if adventure_flag is not None:
                started = self.pokemon_reader.read_gen3_event_flag(self.game_name, int(adventure_flag))
                if started is True:
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
        current_pokedex = self._read_current_pokedex_caught()
        return len(current_pokedex) >= self._get_pokedex_completion_target()
    
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
        current_pokedex = self._read_current_pokedex_caught()
        if len(current_pokedex) < self._get_pokedex_completion_target():
            return False
        
        return True
    
    def _get_pokedex_completion_target(self) -> int:
        """Resolve completion target from loaded achievements, with safe fallbacks."""
        for ach in self.achievements:
            if ach.id.lower().endswith("_pokedex_complete") and ach.target_value is not None:
                try:
                    return max(1, int(ach.target_value))
                except (TypeError, ValueError):
                    continue
        if GAME_CONFIGS_AVAILABLE and self.game_name:
            config = get_game_config(self.game_name)
            if config and config.max_pokemon:
                return int(config.max_pokemon)
        if self.game_name and any(x in self.game_name.lower() for x in ["gold", "silver", "crystal"]):
            return 251
        return 151

    def check_collection(self):
        """Check Pokemon collection and queue updates"""
        if not self.game_name or not self.pokemon_reader:
            return

        # Read current Pokedex.
        current_pokedex = self._read_current_pokedex_caught()

        # Keep party reads separate from catch/achievement responsiveness.
        current_party = list(self._last_party)
        retroarch_unstable = bool(getattr(self.retroarch, "is_unstable_io", lambda: False)())
        allow_live_party = self._collection_baseline_initialized and not retroarch_unstable
        if allow_live_party:
            live_party = self._read_current_party()
            if live_party or not self._last_party:
                current_party = live_party
                self._party_skip_streak = 0
            else:
                current_party = list(self._last_party)
                self._party_skip_streak += 1
                if self._party_skip_streak == 1 or self._party_skip_streak % 20 == 0:
                    log_event(
                        logging.INFO,
                        "party_read_skipped",
                        game=self.game_name,
                        reason="empty_party_read",
                        streak=self._party_skip_streak,
                        io_error_streak=getattr(self.retroarch, "_io_error_streak", 0),
                    )
        elif current_pokedex:
            self._party_skip_streak += 1
            skip_reason = "baseline_pending" if not self._collection_baseline_initialized else "unstable_io"
            if self._party_skip_streak == 1 or self._party_skip_streak % 20 == 0:
                log_event(
                    logging.INFO,
                    "party_read_skipped",
                    game=self.game_name,
                    reason=skip_reason,
                    streak=self._party_skip_streak,
                    io_error_streak=getattr(self.retroarch, "_io_error_streak", 0),
                )

        # First read(s) after game load/start establish a stable baseline.
        if not self._collection_baseline_initialized:
            baseline_confirmations = max(1, int(self._get_validation_profile().get("collection_baseline_confirmations", 2)))

            if not current_pokedex:
                self._collection_wait_streak += 1
                if self._collection_wait_streak == 1 or self._collection_wait_streak % 10 == 0:
                    log_event(
                        logging.INFO,
                        "collection_waiting_for_data",
                        game=self.game_name,
                        streak=self._collection_wait_streak,
                        baseline_confirmations=baseline_confirmations,
                        last_known=len(self._last_pokedex),
                    )

                self._collection_baseline_candidate = []
                self._collection_baseline_candidate_streak = 0

                empty_wait_polls = max(2, int(self._get_validation_profile().get("collection_empty_baseline_wait_polls", 10)))
                if self._collection_wait_streak >= empty_wait_polls:
                    baseline_party: List[Dict] = []
                    if not retroarch_unstable:
                        baseline_party = self._read_current_party()

                    self._last_pokedex = []
                    self._last_party = list(baseline_party)
                    self._collection_baseline_initialized = True
                    self._collection_wait_streak = 0
                    self._baseline_snapshot_pending = False
                    self._baseline_snapshot_wait_polls = 0

                    log_event(
                        logging.INFO,
                        "collection_baseline_established",
                        game=self.game_name,
                        catches=0,
                        party=len(baseline_party),
                        party_sync_deferred=False,
                        reason="empty_timeout",
                    )

                    if baseline_party:
                        self._collection_queue.put({
                            "catches": [],
                            "party": baseline_party,
                            "previous_party": [],
                            "game": self.game_name,
                            "catch_event_type": "caught",
                        })
                    return

                return

            if self._collection_wait_streak:
                log_event(
                    logging.INFO,
                    "collection_data_detected",
                    game=self.game_name,
                    streak=self._collection_wait_streak,
                    catches=len(current_pokedex),
                )
                self._collection_wait_streak = 0

            if current_pokedex == self._collection_baseline_candidate:
                self._collection_baseline_candidate_streak += 1
            else:
                self._collection_baseline_candidate = list(current_pokedex)
                self._collection_baseline_candidate_streak = 1

            if self._collection_baseline_candidate_streak < baseline_confirmations:
                return

            self._last_pokedex = list(current_pokedex)
            self._last_party = list(current_party)
            self._collection_baseline_initialized = True
            self._collection_baseline_candidate = []
            self._collection_baseline_candidate_streak = 0

            # Sync one stable startup snapshot so existing save data uploads reliably.
            if not current_party and current_pokedex:
                self._baseline_snapshot_pending = True
                self._baseline_snapshot_wait_polls = 0
                log_event(
                    logging.INFO,
                    "collection_baseline_established",
                    game=self.game_name,
                    catches=len(current_pokedex),
                    party=len(current_party),
                    party_sync_deferred=True,
                )
                return

            self._baseline_snapshot_pending = False
            self._baseline_snapshot_wait_polls = 0
            log_event(
                logging.INFO,
                "collection_baseline_established",
                game=self.game_name,
                catches=len(current_pokedex),
                party=len(current_party),
                party_sync_deferred=False,
            )
            self._collection_queue.put({
                "catches": list(current_pokedex),
                "party": current_party,
                "previous_party": [],
                "game": self.game_name,
                "catch_event_type": "caught",
            })
            return

        profile = self._get_validation_profile()
        effective_pokedex = list(current_pokedex)
        baseline_snapshot_queued = False
        if self._baseline_snapshot_pending:
            self._baseline_snapshot_wait_polls += 1
            should_flush_baseline = bool(current_party) or self._baseline_snapshot_wait_polls >= 3
            if should_flush_baseline:
                flush_reason = "party_ready" if current_party else "timeout"
                self._collection_queue.put({
                    "catches": list(self._last_pokedex),
                    "party": current_party,
                    "previous_party": [],
                    "game": self.game_name,
                    "catch_event_type": "caught",
                })
                baseline_snapshot_queued = True
                log_event(
                    logging.INFO,
                    "collection_baseline_sync_flushed",
                    game=self.game_name,
                    reason=flush_reason,
                    catches=len(self._last_pokedex),
                    party=len(current_party),
                    polls=self._baseline_snapshot_wait_polls,
                )
                self._baseline_snapshot_pending = False
                self._baseline_snapshot_wait_polls = 0
            elif self._baseline_snapshot_wait_polls == 1 or self._baseline_snapshot_wait_polls % 10 == 0:
                log_event(
                    logging.INFO,
                    "collection_baseline_sync_waiting",
                    game=self.game_name,
                    catches=len(self._last_pokedex),
                    polls=self._baseline_snapshot_wait_polls,
                )

        # Avoid dropping a non-empty Pokedex state on transient empty reads.
        if current_pokedex:
            self._empty_pokedex_streak = 0
        elif self._last_pokedex:
            self._empty_pokedex_streak += 1
            empty_drop_confirmations = max(2, int(profile.get("collection_empty_drop_confirmations", 3)))
            if self._empty_pokedex_streak < empty_drop_confirmations:
                if len(self._last_pokedex) >= 10:
                    self._handle_bad_read("empty_pokedex_after_non_empty")
                else:
                    self._log_warning_throttled(
                        "pokedex_empty_read_ignored",
                        cooldown_s=10.0,
                        throttle_key=f"pokedex_empty_read_ignored:{self.game_name}",
                        game=self.game_name,
                        streak=self._empty_pokedex_streak,
                        held_count=len(self._last_pokedex),
                    )
                effective_pokedex = list(self._last_pokedex)
            else:
                self._empty_pokedex_streak = 0
        else:
            self._empty_pokedex_streak = 0

        # When transitioning from an empty baseline, require a stable non-empty read.
        if not self._last_pokedex and effective_pokedex:
            first_nonempty_confirmations = max(2, int(profile.get("collection_first_nonempty_confirmations", 2)))
            if effective_pokedex == self._collection_baseline_candidate:
                self._collection_baseline_candidate_streak += 1
            else:
                self._collection_baseline_candidate = list(effective_pokedex)
                self._collection_baseline_candidate_streak = 1

            if self._collection_baseline_candidate_streak < first_nonempty_confirmations:
                effective_pokedex = []
            else:
                effective_pokedex = list(self._collection_baseline_candidate)
                self._collection_baseline_candidate = []
                self._collection_baseline_candidate_streak = 0
        elif not effective_pokedex:
            self._collection_baseline_candidate = []
            self._collection_baseline_candidate_streak = 0

        # Find new catches.
        new_catches = [p for p in effective_pokedex if p not in self._last_pokedex]
        lost_catches = [p for p in self._last_pokedex if p not in effective_pokedex]

        # Guard against bad memory reads causing impossible bulk catch spikes.
        if len(new_catches) > profile["max_new_catches_per_poll"]:
            startup_window_polls = max(1, int(profile.get("startup_snapshot_window_polls", 30)))
            within_startup_window = self._achievement_poll_count <= startup_window_polls
            likely_startup_snapshot = within_startup_window and len(effective_pokedex) >= max(20, len(self._last_pokedex) + (profile["max_new_catches_per_poll"] * 3))
            if likely_startup_snapshot:
                log_event(
                    logging.INFO,
                    "collection_baseline_reset",
                    game=self.game_name,
                    baseline=len(self._last_pokedex),
                    observed=len(effective_pokedex),
                )
                self._collection_queue.put({
                    "catches": list(effective_pokedex),
                    "previous_party": list(self._last_party),
                    "party": current_party,
                    "game": self.game_name,
                    "catch_event_type": "caught",
                })
                self._last_pokedex = list(effective_pokedex)
                self._last_party = list(current_party)
                self._bad_read_streak = 0
                return

            # If the read both adds and removes many IDs at once, treat it as churn/noise.
            if lost_catches and self._last_pokedex and effective_pokedex:
                self._record_anomaly(
                    "collection_churn_ignored",
                    game=self.game_name,
                    added_count=len(new_catches),
                    removed_count=len(lost_catches),
                    previous_count=len(self._last_pokedex),
                    observed_count=len(effective_pokedex),
                )
                churn_key = f"collection_churn_ignored:{self.game_name}"
                now = time.monotonic()
                last = float(self._warning_last_log.get(churn_key, 0.0))
                if (now - last) >= 20.0:
                    self._warning_last_log[churn_key] = now
                    log_event(
                        logging.INFO,
                        "collection_churn_ignored",
                        game=self.game_name,
                        added_count=len(new_catches),
                        removed_count=len(lost_catches),
                        previous_count=len(self._last_pokedex),
                        observed_count=len(effective_pokedex),
                    )
                effective_pokedex = list(self._last_pokedex)
                new_catches = []
                self._bad_read_streak = 0
            else:
                self._record_anomaly("collection_spike_ignored", game=self.game_name, spike_count=len(new_catches), threshold=profile["max_new_catches_per_poll"])
                self._log_warning_throttled("collection_spike_ignored", cooldown_s=15.0, throttle_key=f"collection_spike_ignored:{self.game_name}", game=self.game_name, spike_count=len(new_catches), threshold=profile["max_new_catches_per_poll"])
                self._handle_bad_read("bulk_catch_spike")
                effective_pokedex = list(self._last_pokedex)
                new_catches = []
        else:
            self._bad_read_streak = 0

        # Find party changes (including slot/order changes and duplicate species).
        party_read_meta = self.pokemon_reader.get_last_party_read_meta() if self.pokemon_reader else {}
        party_changed = current_party != self._last_party
        drop_pending_set = False

        def _party_signature(party_members: List[Dict]) -> tuple:
            signature_rows = []
            for member in party_members:
                if not isinstance(member, dict):
                    continue
                try:
                    signature_rows.append((
                        int(member.get("slot", 0)),
                        int(member.get("id", 0)),
                        int(member.get("level", 0)) if member.get("level") is not None else None,
                    ))
                except (TypeError, ValueError):
                    continue
            return tuple(sorted(signature_rows))

        if party_changed:
            expected_count = party_read_meta.get("expected_count")
            decoded_count = party_read_meta.get("decoded_count")
            incomplete_read = bool(party_read_meta.get("incomplete"))
            candidate_signature = _party_signature(current_party)
            previous_count = len(self._last_party)
            current_count = len(current_party)

            should_confirm_drop = (
                current_count < previous_count
                and incomplete_read
            )

            if should_confirm_drop:
                pending = self._pending_party_change or {}
                is_same_candidate = (
                    pending.get("signature") == candidate_signature
                    and int(pending.get("previous_count", -1)) == int(previous_count)
                )
                if is_same_candidate:
                    self._pending_party_change = None
                    log_event(
                        logging.INFO,
                        "party_drop_confirmed_after_retry",
                        game=self.game_name,
                        previous_count=previous_count,
                        current_count=current_count,
                        expected_count=expected_count,
                        decoded_count=decoded_count,
                    )
                else:
                    self._pending_party_change = {
                        "signature": candidate_signature,
                        "previous_count": int(previous_count),
                    }
                    drop_pending_set = True
                    log_event(
                        logging.INFO,
                        "party_read_skipped",
                        game=self.game_name,
                        reason="party_drop_pending_confirmation",
                        previous_count=previous_count,
                        current_count=current_count,
                        expected_count=expected_count,
                        decoded_count=decoded_count,
                    )
                    party_changed = False
                    current_party = list(self._last_party)

        if party_changed:
            self._pending_party_change = None
            slots: List[Dict[str, object]] = []
            for member in current_party:
                if not isinstance(member, dict):
                    continue
                dex_id = int(member.get("id", 0))
                slots.append({
                    "slot": int(member.get("slot", 0)),
                    "id": dex_id,
                    "name": member.get("name") if isinstance(member.get("name"), str) else (self.pokemon_reader.get_pokemon_name(dex_id) if dex_id > 0 else f"Pokemon #{dex_id}"),
                    "level": member.get("level"),
                    "shiny": bool(member.get("shiny", False)),
                    "shiny_xor": member.get("_shiny_xor"),
                    "personality": member.get("_personality"),
                    "ot_id": member.get("_ot_id"),
                    "gender": member.get("gender"),
                    "nature": member.get("nature"),
                    "ability": member.get("ability"),
                    "moves": member.get("moves") if isinstance(member.get("moves"), list) else [],
                })
            log_event(
                logging.INFO,
                "party_state_changed",
                game=self.game_name,
                previous_count=len(self._last_party),
                current_count=len(current_party),
            )
            for slot_info in sorted(slots, key=lambda s: int(s.get("slot", 0))):
                line = _format_party_slot_line(
                    slot_info,
                    debug_style=True,
                    name_resolver=self.pokemon_reader.get_pokemon_name if self.pokemon_reader else None,
                )
                if line:
                    log_fields: Dict[str, object] = {
                        "game": self.game_name,
                        "text": line,
                    }
                    for key in ("slot", "id", "shiny", "shiny_xor", "personality", "ot_id"):
                        value = slot_info.get(key)
                        if value is not None:
                            log_fields[key] = value
                    log_event(logging.INFO, "party_slot", **log_fields)
        else:
            if not drop_pending_set and current_party == self._last_party:
                self._pending_party_change = None

        # Queue updates if there are changes.
        if (new_catches or party_changed) and not baseline_snapshot_queued:
            self._collection_queue.put({
                "previous_party": list(self._last_party),
                "catches": new_catches,
                "party": current_party,
                "game": self.game_name,
                "catch_event_type": "new_addition",
            })

        # Update last known state.
        self._last_pokedex = list(effective_pokedex)
        self._last_party = list(current_party)

    def post_unlock_to_platform(self, achievement: Achievement):
        """Queue achievement unlock for API posting"""
        if self.api and self.game_id:
            event_id = f"unlock:{self.game_id}:{achievement.id}"
            self._api_queue.put({"type": "achievement", "achievement": achievement, "event_id": event_id, "confidence": "high"})
    
    def post_collection_to_platform(self, catches: List[int], party: List[Dict], game: str, previous_party: Optional[List[Dict]] = None):
        """Queue collection update for API posting"""
        if self.api:
            payload_key = json.dumps({"catches": sorted(catches), "party": party, "previous_party": previous_party or [], "game": game}, sort_keys=True, default=str)
            event_id = "collection:" + sha256(payload_key.encode()).hexdigest()[:24]
            confidence = "high" if len(catches) <= 2 else "medium"
            self._api_queue.put({
                "type": "collection",
                "catches": catches,
                "party": party,
                "previous_party": previous_party or [],
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
        if self._running and self._thread and self._thread.is_alive():
            log_event(logging.INFO, "poll_thread_already_running", game=self.game_name)
            return

        self._running = True
        self._poll_heartbeat_count = 0
        self._thread = threading.Thread(target=self._poll_loop, args=(interval_ms,), daemon=True)
        self._thread.start()
        log_event(
            logging.INFO,
            "poll_thread_started",
            game=self.game_name,
            interval_ms=int(interval_ms),
            thread_id=self._thread.ident,
        )

    def stop_polling(self):
        """Stop polling"""
        self._running = False
        log_event(logging.INFO, "poll_thread_stop_requested", game=self.game_name)

    def _poll_loop(self, interval_ms: int):
        """Background polling loop"""
        while self._running:
            if self.retroarch.connected and self.achievements:
                if bool(getattr(self.retroarch, "is_waiting_for_launch", lambda: False)()):
                    self._poll_disconnected_streak += 1
                    time.sleep(interval_ms / 1000)
                    continue

                self._poll_disconnected_streak = 0
                self._poll_heartbeat_count += 1
                self._cached_pokedex_for_poll = None
                should_trace_poll = self._poll_heartbeat_count == 1 or self._poll_heartbeat_count % 20 == 0
                if should_trace_poll:
                    log_event(
                        logging.INFO,
                        "poll_heartbeat",
                        game=self.game_name,
                        poll=self._poll_heartbeat_count,
                        achievements=len(self.achievements),
                        baseline=self._collection_baseline_initialized,
                        last_pokedex=len(self._last_pokedex),
                        last_party=len(self._last_party),
                    )
                    log_event(
                        logging.INFO,
                        "poll_stage_start",
                        game=self.game_name,
                        poll=self._poll_heartbeat_count,
                        stage="achievements",
                    )

                ach_started = time.perf_counter()
                try:
                    self.check_achievements()
                except Exception as exc:
                    self._record_anomaly(
                        "poll_loop_exception",
                        game=self.game_name,
                        stage="achievements",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    log_event(
                        logging.ERROR,
                        "poll_loop_exception",
                        game=self.game_name,
                        stage="achievements",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                finally:
                    ach_ms = int((time.perf_counter() - ach_started) * 1000)
                    if ach_ms >= 1500:
                        log_event(
                            logging.INFO,
                            "poll_stage_duration",
                            game=self.game_name,
                            poll=self._poll_heartbeat_count,
                            stage="achievements",
                            duration_ms=ach_ms,
                        )

                if should_trace_poll:
                    log_event(
                        logging.INFO,
                        "poll_stage_start",
                        game=self.game_name,
                        poll=self._poll_heartbeat_count,
                        stage="collection",
                    )

                collection_started = time.perf_counter()
                try:
                    self.check_collection()
                except Exception as exc:
                    self._record_anomaly(
                        "poll_loop_exception",
                        game=self.game_name,
                        stage="collection",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    log_event(
                        logging.ERROR,
                        "poll_loop_exception",
                        game=self.game_name,
                        stage="collection",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                finally:
                    collection_ms = int((time.perf_counter() - collection_started) * 1000)
                    if collection_ms >= 1500:
                        log_event(
                            logging.INFO,
                            "poll_stage_duration",
                            game=self.game_name,
                            poll=self._poll_heartbeat_count,
                            stage="collection",
                            duration_ms=collection_ms,
                        )
            else:
                self._poll_disconnected_streak += 1
                if self._poll_disconnected_streak == 1:
                    log_event(
                        logging.INFO,
                        "poll_waiting_connection",
                        game=self.game_name,
                        streak=self._poll_disconnected_streak,
                        connected=bool(self.retroarch.connected),
                        has_achievements=bool(self.achievements),
                    )
            time.sleep(interval_ms / 1000)

        log_event(
            logging.INFO,
            "poll_thread_exited",
            game=self.game_name,
            polls=self._poll_heartbeat_count,
        )

class PokeAchieveGUI:
    """Main GUI Application"""
    
    RARITY_COLORS = {
        "common": "#95a5a6",
        "uncommon": "#2ecc71", 
        "rare": "#3498db",
        "epic": "#9b59b6",
        "legendary": "#f39c12"
    }

    GAME_THEMES = {
        "default": {"bg": "#f3f4f6", "fg": "#111827", "accent": "#2563eb", "subtle": "#4b5563"},
        "Pokemon Red": {"bg": "#fef2f2", "fg": "#7f1d1d", "accent": "#dc2626", "subtle": "#991b1b"},
        "Pokemon Blue": {"bg": "#eff6ff", "fg": "#1e3a8a", "accent": "#2563eb", "subtle": "#1d4ed8"},
        "Pokemon Yellow": {"bg": "#fffbeb", "fg": "#713f12", "accent": "#eab308", "subtle": "#a16207"},
        "Pokemon Gold": {"bg": "#fffbeb", "fg": "#78350f", "accent": "#d97706", "subtle": "#92400e"},
        "Pokemon Silver": {"bg": "#f8fafc", "fg": "#334155", "accent": "#64748b", "subtle": "#475569"},
        "Pokemon Crystal": {"bg": "#ecfeff", "fg": "#0e7490", "accent": "#06b6d4", "subtle": "#0891b2"},
        "Pokemon Ruby": {"bg": "#fff1f2", "fg": "#881337", "accent": "#e11d48", "subtle": "#9f1239"},
        "Pokemon Sapphire": {"bg": "#eff6ff", "fg": "#1e3a8a", "accent": "#2563eb", "subtle": "#1d4ed8"},
        "Pokemon Emerald": {"bg": "#ecfdf5", "fg": "#14532d", "accent": "#059669", "subtle": "#047857"},
        "Pokemon FireRed": {"bg": "#fff7ed", "fg": "#9a3412", "accent": "#ea580c", "subtle": "#c2410c"},
        "Pokemon LeafGreen": {"bg": "#f0fdf4", "fg": "#14532d", "accent": "#22c55e", "subtle": "#15803d"},
    }
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PokeAchieve Tracker v1.9")
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
        self.poll_interval = self.config.get("poll_interval", 1000)
        self.api_sync_enabled = self.config.get("api_sync", True)
        self._status_check_in_flight = False
        self._max_log_lines = 500
        self._max_recent_lines = 200
        self._max_catch_lines = 200
        self._api_worker_thread: Optional[threading.Thread] = None
        self._api_worker_stop = threading.Event()
        self._api_status_state = "Not configured"
        self._last_sync_status = "Idle"
        self._last_api_error = ""
        self._retry_count = 0
        self.sent_events_file = self.data_dir / "sent_events.json"
        self._sent_event_ids = self._load_sent_events()
        self._load_validation_profiles()
        self._party_slot_widgets: Dict[int, Dict[str, object]] = {}
        self._party_sprite_cache: Dict[Tuple[str, int, bool], object] = {}
        self._party_sprite_pending: Set[Tuple[str, int, bool]] = set()
        self._party_sprite_failed: Set[Tuple[str, int, bool]] = set()
        self._party_gender_badge_cache: Dict[Tuple[str, str], object] = {}
        self._party_gender_badge_missing: Set[Tuple[str, str]] = set()
        self._party_shiny_badge_cache: Dict[str, object] = {}
        self._party_shiny_badge_missing: Set[str] = set()
        self._party_type_icon_cache: Dict[Tuple[str, str], object] = {}
        self._party_type_icon_missing: Set[Tuple[str, str]] = set()
        self._species_type_cache: Dict[int, Dict[str, object]] = {}
        self._species_type_pending: Set[int] = set()
        self._species_type_failed: Set[int] = set()
        self._party_display_last_party: List[Dict] = []
        self._party_display_last_game = ""
        self._party_sprite_size = 64
        self._party_sprite_cache_dir = self.data_dir / "sprites"
        self._party_sprite_cache_dir.mkdir(exist_ok=True)
        self._party_gender_badge_assets_dir = self.script_dir / "gui" / "assets" / "gender_badges"
        if not self._party_gender_badge_assets_dir.exists():
            self._party_gender_badge_assets_dir = self.script_dir / "assets" / "gender_badges"
        self._party_shiny_badge_assets_dir = self.script_dir / "gui" / "assets" / "shiny_badges"
        if not self._party_shiny_badge_assets_dir.exists():
            self._party_shiny_badge_assets_dir = self.script_dir / "assets" / "shiny_badges"
        self._party_type_icon_assets_dir = self.script_dir / "gui" / "assets" / "type_icons"
        if not self._party_type_icon_assets_dir.exists():
            self._party_type_icon_assets_dir = self.script_dir / "assets" / "type_icons"

        self._hunt_modes = [
            "Soft Reset Hunt",
            "Wild Encounter Hunt",
            "Fishing Encounter Hunt",
            "Hatching Egg Hunt",
        ]
        self._hunt_game_options = self._build_hunt_game_options()
        # Build these lazily to keep initial window open responsive.
        self._hunt_encounter_catalog: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._hunt_route_options: Dict[str, List[str]] = {}
        self._hunt_fishing_options: Dict[str, List[str]] = {}
        self.hunt_mode_var = tk.StringVar(value=self._hunt_modes[0])
        self.hunt_game_var = tk.StringVar(value=self._hunt_game_options[0] if self._hunt_game_options else "")
        self.hunt_route_var = tk.StringVar(value="Any Soft Reset")
        self.hunt_target_var = tk.StringVar(value="")
        self.hunt_profiles_file = self.data_dir / "hunt_profiles.json"
        self._hunt_profiles = self._load_hunt_profiles()
        self._hunt_profile_applying = False
        self._hunt_active = False
        self._hunt_counter = 0
        self._hunt_phase_count = 0
        self._hunt_last_enemy_signature: Optional[str] = None
        self._hunt_last_target_signature: Optional[str] = None
        self._hunt_enemy_present = False
        self._hunt_last_enemy_seen_at = 0.0
        self._hunt_target_present = False
        self._hunt_recent_other_species: deque[int] = deque(maxlen=24)
        self._hunt_last_waiting_state = bool(self.retroarch.is_waiting_for_launch())
        self._hunt_soft_reset_reset_pending = False
        self._hunt_soft_reset_seen_in_pokedex = False
        self._hunt_soft_reset_target_id = 0
        self._hunt_alerted_signatures: Set[str] = set()
        self._hunt_last_party_snapshot: Dict[int, Dict[str, object]] = {}
        self._hunt_initialized = False
        self._hunt_species_counts: Dict[int, int] = {}
        self._hunt_species_count_labels: Dict[int, ttk.Label] = {}
        self._hunt_last_raw_log_key: Optional[str] = None
        self._hunt_last_raw_none_log_at = 0.0
        self._hunt_target_sprite_label: Optional[ttk.Label] = None
        self._hunt_target_name_label: Optional[ttk.Label] = None
        self._hunt_target_type_frame: Optional[ttk.Frame] = None
        self._hunt_target_type_labels: List[ttk.Label] = []
        self._hunt_target_meta_label: Optional[ttk.Label] = None
        self._hunt_counter_label: Optional[ttk.Label] = None
        self._hunt_phase_label: Optional[ttk.Label] = None
        self._hunt_mode_hint_label: Optional[ttk.Label] = None
        self._hunt_other_sprites_frame: Optional[ttk.Frame] = None
        self._hunt_other_sprite_labels: List[ttk.Label] = []
        self._hunt_available_canvas: Optional[tk.Canvas] = None
        self._hunt_available_scrollbar: Optional[ttk.Scrollbar] = None
        self._hunt_available_window_id: Optional[int] = None
        self._hunt_route_label: Optional[ttk.Label] = None
        self._hunt_route_combo: Optional[ttk.Combobox] = None
        self._hunt_target_combo: Optional[ttk.Combobox] = None
        self._hunt_game_combo: Optional[ttk.Combobox] = None
        self._hunt_mode_combo: Optional[ttk.Combobox] = None
        self._hunt_start_btn: Optional[ttk.Button] = None
        self._hunt_pause_btn: Optional[ttk.Button] = None

        self._build_ui()
        self.root.after(10, self._prime_hunt_catalog_async)
        self._start_status_check()
        self.root.after(250, self._maybe_run_setup_wizard)

    def _prime_hunt_catalog_async(self):
        """Load hunt encounter catalog in a worker thread to reduce startup jank."""

        def worker():
            catalog = self._build_hunt_encounter_catalog()
            self._hunt_encounter_catalog = catalog
            self._hunt_route_options = self._build_default_hunt_route_options()
            self._hunt_fishing_options = self._build_default_hunt_fishing_options()
            self.root.after(0, self._apply_hunt_catalog_ready)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_hunt_catalog_ready(self):
        """Refresh hunt selectors once async catalog loading completes."""
        self._update_hunt_mode_controls()
        self._refresh_hunt_targets()
    
    def _configure_styles(self):
        """Apply a cleaner, modern ttk theme and spacing."""
        style = ttk.Style(self.root)
        self._ttk_style = style
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
        self._apply_game_theme(None)

    def _apply_game_theme(self, game_name: Optional[str]):
        """Apply lightweight color accents based on the detected game."""
        style = getattr(self, "_ttk_style", None)
        if not isinstance(style, ttk.Style):
            return

        theme_key = str(game_name or "").strip()
        palette = self.GAME_THEMES.get(theme_key, self.GAME_THEMES["default"])

        style.configure("TFrame", background=palette["bg"])
        style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        style.configure("Subtle.TLabel", background=palette["bg"], foreground=palette["subtle"])
        style.configure("TNotebook", background=palette["bg"])
        style.map("TNotebook.Tab", background=[("selected", palette["accent"]), ("!selected", palette["bg"])], foreground=[("selected", "#ffffff"), ("!selected", palette["fg"])])
        style.configure("Primary.TButton", background=palette["accent"], foreground="#ffffff")
        try:
            self.root.configure(bg=palette["bg"])
        except tk.TclError:
            pass

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
    
    def _load_hunt_profiles(self) -> Dict[str, Any]:
        default_data: Dict[str, Any] = {"version": 1, "games": {}}
        if not self.hunt_profiles_file.exists():
            return default_data
        try:
            with open(self.hunt_profiles_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("games"), dict):
                data.setdefault("version", 1)
                return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            log_event(logging.WARNING, "hunt_profiles_load_failed", file=str(self.hunt_profiles_file), error=str(exc))
        return default_data

    def _save_hunt_profiles(self):
        self._hunt_profiles.setdefault("version", 1)
        self._hunt_profiles.setdefault("games", {})
        try:
            with open(self.hunt_profiles_file, "w") as f:
                json.dump(self._hunt_profiles, f, indent=2)
        except OSError as exc:
            log_event(logging.WARNING, "hunt_profiles_save_failed", file=str(self.hunt_profiles_file), error=str(exc))

    def _get_hunt_profile_store_for_game(self, game_name: str, *, create: bool = False) -> Optional[Dict[str, Any]]:
        game_key = (game_name or "").strip()
        if not game_key:
            return None

        games = self._hunt_profiles.get("games")
        if not isinstance(games, dict):
            if not create:
                return None
            games = {}
            self._hunt_profiles["games"] = games

        game_store = games.get(game_key)
        if not isinstance(game_store, dict):
            if not create:
                return None
            game_store = {"last_profile_key": "", "profiles": {}}
            games[game_key] = game_store

        profiles = game_store.get("profiles")
        if not isinstance(profiles, dict):
            if not create:
                return None
            game_store["profiles"] = {}

        if not isinstance(game_store.get("last_profile_key"), str):
            game_store["last_profile_key"] = ""

        return game_store

    def _build_hunt_profile_key(self, mode: str, route_name: str, target_id: int) -> str:
        safe_mode = (mode or "").strip()
        safe_route = (route_name or "").strip()
        try:
            safe_target_id = int(target_id)
        except (TypeError, ValueError):
            safe_target_id = 0
        if safe_target_id < 0:
            safe_target_id = 0
        return f"{safe_mode}|{safe_route}|{safe_target_id}"
    def _load_validation_profiles(self):
        profile_path = self.script_dir / "profiles.json"
        if not profile_path.exists():
            self.tracker.set_validation_profiles({})
            return
        try:
            with open(profile_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.tracker.set_validation_profiles(data)
            else:
                self.tracker.set_validation_profiles({})
        except (OSError, json.JSONDecodeError, ValueError):
            self.tracker.set_validation_profiles({})

    def _update_sync_meta_labels(self):
        self.sync_status_label.configure(text=f"Sync: {self._last_sync_status}")
        self.retry_status_label.configure(text=f"Retries: {self._retry_count}")
        error_text = self._last_api_error if self._last_api_error else "None"
        self.api_error_label.configure(text=f"Last API Error: {error_text[:90]}")

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
            "retry_count": self._retry_count,
            "last_api_error": self._last_api_error,
            "queue": {
                "api_pending": self.tracker._api_queue.qsize(),
                "collection_pending": self.tracker._collection_queue.qsize(),
                "unlock_pending": self.tracker._unlock_queue.qsize(),
            },
            "validation_profile": self.tracker._get_validation_profile() if self.tracker.game_name else None,
            "recent_anomalies": self.tracker.recent_anomalies[-25:],
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
        
        # Collection Tab
        self.collection_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.collection_frame, text="Collection")
        self._build_collection_tab()

        # Shiny Hunt Tab
        self.hunt_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.hunt_frame, text="Shiny Hunt")
        self._build_hunt_tab()
        
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

        self.retry_status_label = ttk.Label(conn_frame, text="Retries: 0")
        self.retry_status_label.pack(anchor=tk.W, pady=1)

        self.api_error_label = ttk.Label(conn_frame, text="Last API Error: None")
        self.api_error_label.pack(anchor=tk.W, pady=1)

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
            text="Start Tracking",
            command=self._start_tracking,
            style="Primary.TButton"
        )
        self.start_btn.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self.stop_btn = ttk.Button(
            controls_frame,
            text="Stop",
            command=self._stop_tracking,
            state='disabled'
        )
        self.stop_btn.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        ttk.Button(controls_frame, text="Sync", command=self._sync_with_server).grid(
            row=0, column=2, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="Settings", command=self._show_settings).grid(
            row=0, column=3, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="Clear Data", command=self._clear_app_data).grid(
            row=0, column=4, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(controls_frame, text="Export Diagnostics", command=self._export_diagnostics).grid(
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

        self.party_cards_frame = ttk.Frame(party_frame)
        self.party_cards_frame.pack(fill=tk.X, expand=True)

        for col in range(6):
            self.party_cards_frame.columnconfigure(col, weight=1, uniform="party_slots")

        self._party_slot_widgets = {}
        for slot in range(1, 7):
            card = ttk.LabelFrame(self.party_cards_frame, text=f"Slot {slot}", padding=8)
            card.grid(row=0, column=slot - 1, sticky="nsew", padx=4, pady=4)

            header_frame = ttk.Frame(card)
            header_frame.pack(anchor=tk.W, pady=(0, 4))

            title_label = ttk.Label(
                header_frame,
                text="Lv.-- Unknown",
                justify=tk.LEFT,
                anchor=tk.W,
                wraplength=136,
                font=("Segoe UI", 9, "bold"),
            )
            title_label.pack(side=tk.LEFT)

            gender_label = ttk.Label(
                header_frame,
                text="",
                justify=tk.RIGHT,
                anchor=tk.E,
                width=0,
                font=("Segoe UI Symbol", 11, "bold"),
            )
            gender_label.pack(side=tk.LEFT, padx=(0, 0))

            sprite_frame = ttk.Frame(card)
            sprite_frame.pack(fill=tk.X, pady=(0, 2))

            sprite_anchor = ttk.Frame(sprite_frame)
            sprite_anchor.pack(anchor=tk.CENTER)

            sprite_label = ttk.Label(sprite_anchor, text="No Sprite", justify=tk.CENTER, anchor=tk.CENTER)
            sprite_label.pack(anchor=tk.CENTER)

            shiny_label = ttk.Label(
                sprite_anchor,
                text="",
                justify=tk.RIGHT,
                anchor=tk.NE,
                width=0,
            )
            shiny_label.place(in_=sprite_label, relx=1.0, x=0, y=0, anchor="ne")

            type_frame = ttk.Frame(card)
            type_frame.pack(anchor=tk.CENTER, pady=(0, 4))
            type1_label = ttk.Label(type_frame, text="")
            type1_label.pack(side=tk.LEFT, padx=(0, 2))
            type2_label = ttk.Label(type_frame, text="")
            type2_label.pack(side=tk.LEFT, padx=(0, 0))

            details_label = ttk.Label(
                card,
                text="Ability: -\nNature: -",
                justify=tk.LEFT,
                anchor=tk.W,
                wraplength=160,
            )
            details_label.pack(fill=tk.X, pady=(0, 4))

            moves_label = ttk.Label(
                card,
                text="Moves:\n-\n-\n-\n-",
                justify=tk.LEFT,
                anchor=tk.W,
                wraplength=160,
            )
            moves_label.pack(fill=tk.X)

            self._party_slot_widgets[slot] = {
                "title": title_label,
                "gender": gender_label,
                "shiny": shiny_label,
                "sprite": sprite_label,
                "type1": type1_label,
                "type2": type2_label,
                "details": details_label,
                "moves": moves_label,
            }

        self._update_party_display([], "")

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

    def _build_hunt_game_options(self) -> List[str]:
        """Gen 1 games are excluded (no shiny), and order follows gen/release."""
        preferred_order = [
            "Pokemon Gold",
            "Pokemon Silver",
            "Pokemon Crystal",
            "Pokemon Ruby",
            "Pokemon Sapphire",
            "Pokemon FireRed",
            "Pokemon LeafGreen",
            "Pokemon Emerald",
        ]

        options: List[str] = []
        reader = self.tracker.pokemon_reader if self.tracker else None
        for game_name in preferred_order:
            if game_name not in self.tracker.GAME_IDS:
                continue
            config = reader.get_game_config(game_name) if reader else None
            try:
                gen = int(config.get("gen", 1)) if isinstance(config, dict) else 1
            except (TypeError, ValueError):
                gen = 1
            if gen <= 1:
                continue
            options.append(game_name)

        # Include any additional supported non-Gen1 games not in preferred ordering.
        extras = [name for name in self.tracker.GAME_IDS.keys() if name not in options]
        for game_name in sorted(extras, key=lambda g: int(self.tracker.GAME_IDS.get(g, 9999))):
            config = reader.get_game_config(game_name) if reader else None
            try:
                gen = int(config.get("gen", 1)) if isinstance(config, dict) else 1
            except (TypeError, ValueError):
                gen = 1
            if gen <= 1:
                continue
            options.append(game_name)

        return options

    def _build_hunt_encounter_catalog(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Load generated per-game wild/fishing pools and merge soft-reset metadata."""
        catalog: Dict[str, Dict[str, Dict[str, Any]]] = {}

        catalog_path = self.script_dir / "hunt_encounter_catalog.json"
        if catalog_path.exists():
            try:
                with open(catalog_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    catalog = loaded
            except (OSError, json.JSONDecodeError, ValueError):
                catalog = {}

        soft_reset_metadata = self._build_hunt_soft_reset_metadata()
        default_soft_reset = self._default_hunt_soft_reset_categories()

        for game_name in self._hunt_game_options:
            game_block = catalog.get(game_name)
            if not isinstance(game_block, dict):
                game_block = {}

            random_entries = game_block.get("random") if isinstance(game_block.get("random"), dict) else {}
            fishing_entries = game_block.get("fishing") if isinstance(game_block.get("fishing"), dict) else {}

            normalized_random: Dict[str, List[int]] = {}
            for key, value in random_entries.items():
                if not isinstance(key, str):
                    continue
                ids = value if isinstance(value, list) else []
                normalized_random[key] = self._normalize_hunt_species_ids_for_game(game_name, ids)

            normalized_fishing: Dict[str, List[int]] = {}
            for key, value in fishing_entries.items():
                if not isinstance(key, str):
                    continue
                ids = value if isinstance(value, list) else []
                normalized_fishing[key] = self._normalize_hunt_species_ids_for_game(game_name, ids)

            all_random_ids: Set[int] = set()
            for key, ids in normalized_random.items():
                if key != "Any Route / Area":
                    all_random_ids.update(ids)
            if "Any Route / Area" in normalized_random and normalized_random["Any Route / Area"]:
                all_random_ids.update(normalized_random["Any Route / Area"])
            normalized_random["Any Route / Area"] = sorted(all_random_ids)

            all_fishing_ids: Set[int] = set()
            for key, ids in normalized_fishing.items():
                if key != "Any Fishing Spot":
                    all_fishing_ids.update(ids)
            if "Any Fishing Spot" in normalized_fishing and normalized_fishing["Any Fishing Spot"]:
                all_fishing_ids.update(normalized_fishing["Any Fishing Spot"])
            normalized_fishing["Any Fishing Spot"] = sorted(all_fishing_ids)

            soft_reset_for_game = soft_reset_metadata.get(game_name)
            if not isinstance(soft_reset_for_game, dict):
                soft_reset_for_game = dict(default_soft_reset)

            game_block["random"] = normalized_random
            game_block["fishing"] = normalized_fishing
            game_block["soft_reset"] = soft_reset_for_game
            catalog[game_name] = game_block

        return catalog

    def _default_hunt_soft_reset_categories(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "Any Soft Reset": [],
            "Starters": [],
            "Trades": [],
            "Gift": [],
            "Stationary": [],
        }

    def _build_hunt_soft_reset_metadata(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        def entry(species_id: int, *, location: str = "", level: Optional[int] = None, npc: str = "") -> Dict[str, Any]:
            payload: Dict[str, Any] = {"id": int(species_id)}
            if location:
                payload["location"] = location
            if level is not None:
                payload["level"] = int(level)
            if npc:
                payload["npc"] = npc
            return payload

        data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            "Pokemon Gold": {
                "Starters": [
                    entry(152, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(155, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(158, location="New Bark Town", level=5, npc="Professor Elm"),
                ],
                "Trades": [
                    entry(95, location="Violet City", level=3, npc="Youngster in Pokemon Center"),
                    entry(66, location="Goldenrod City", level=10, npc="Department Store NPC"),
                    entry(100, location="Olivine City", level=20, npc="Pokemon Center NPC"),
                    entry(122, location="Route 2", level=10, npc="Gatehouse NPC"),
                ],
                "Gift": [
                    entry(175, location="Violet City", level=5, npc="Professor Elm's Aide"),
                    entry(133, location="Goldenrod City", level=20, npc="Bill"),
                    entry(213, location="Cianwood City", level=15, npc="Man in house"),
                    entry(236, location="Mt. Mortar", level=10, npc="Kiyo"),
                    entry(147, location="Dragon's Den", level=15, npc="Elder"),
                ],
                "Stationary": [
                    entry(185, location="Route 36", level=20),
                    entry(130, location="Lake of Rage", level=30),
                    entry(143, location="Route 11", level=50),
                    entry(243, location="Roaming Johto", level=40),
                    entry(244, location="Roaming Johto", level=40),
                    entry(245, location="Roaming Johto", level=40),
                    entry(249, location="Whirl Islands", level=40),
                    entry(250, location="Tin Tower", level=40),
                ],
            },
            "Pokemon Silver": {
                "Starters": [
                    entry(152, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(155, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(158, location="New Bark Town", level=5, npc="Professor Elm"),
                ],
                "Trades": [
                    entry(95, location="Violet City", level=3, npc="Youngster in Pokemon Center"),
                    entry(66, location="Goldenrod City", level=10, npc="Department Store NPC"),
                    entry(100, location="Olivine City", level=20, npc="Pokemon Center NPC"),
                    entry(122, location="Route 2", level=10, npc="Gatehouse NPC"),
                ],
                "Gift": [
                    entry(175, location="Violet City", level=5, npc="Professor Elm's Aide"),
                    entry(133, location="Goldenrod City", level=20, npc="Bill"),
                    entry(213, location="Cianwood City", level=15, npc="Man in house"),
                    entry(236, location="Mt. Mortar", level=10, npc="Kiyo"),
                    entry(147, location="Dragon's Den", level=15, npc="Elder"),
                ],
                "Stationary": [
                    entry(185, location="Route 36", level=20),
                    entry(130, location="Lake of Rage", level=30),
                    entry(143, location="Route 11", level=50),
                    entry(243, location="Roaming Johto", level=40),
                    entry(244, location="Roaming Johto", level=40),
                    entry(245, location="Roaming Johto", level=40),
                    entry(249, location="Whirl Islands", level=70),
                    entry(250, location="Tin Tower", level=40),
                ],
            },
            "Pokemon Crystal": {
                "Starters": [
                    entry(152, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(155, location="New Bark Town", level=5, npc="Professor Elm"),
                    entry(158, location="New Bark Town", level=5, npc="Professor Elm"),
                ],
                "Trades": [
                    entry(95, location="Violet City", level=3, npc="Youngster in Pokemon Center"),
                    entry(66, location="Goldenrod City", level=10, npc="Department Store NPC"),
                    entry(100, location="Olivine City", level=20, npc="Pokemon Center NPC"),
                    entry(122, location="Route 2", level=10, npc="Gatehouse NPC"),
                ],
                "Gift": [
                    entry(175, location="Violet City", level=5, npc="Professor Elm's Aide"),
                    entry(133, location="Goldenrod City", level=20, npc="Bill"),
                    entry(213, location="Cianwood City", level=15, npc="Man in house"),
                    entry(236, location="Mt. Mortar", level=10, npc="Kiyo"),
                    entry(147, location="Dragon's Den", level=15, npc="Elder"),
                ],
                "Stationary": [
                    entry(185, location="Route 36", level=20),
                    entry(130, location="Lake of Rage", level=30),
                    entry(143, location="Route 11", level=50),
                    entry(243, location="Roaming Johto", level=40),
                    entry(244, location="Roaming Johto", level=40),
                    entry(245, location="Roaming Johto", level=40),
                    entry(249, location="Whirl Islands", level=60),
                    entry(250, location="Tin Tower", level=60),
                    entry(251, location="Ilex Forest", level=30),
                ],
            },
            "Pokemon Ruby": {
                "Starters": [
                    entry(252, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(255, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(258, location="Littleroot Town", level=5, npc="Professor Birch"),
                ],
                "Trades": [
                    entry(270, location="Rustboro City", level=5, npc="School Kid in house"),
                    entry(273, location="Fortree City", level=13, npc="Pokemon Center NPC"),
                    entry(300, location="Pacifidlog Town", level=15, npc="Pokemon Fan in house"),
                    entry(311, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                    entry(312, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                ],
                "Gift": [
                    entry(351, location="Weather Institute", level=25, npc="Scientist"),
                    entry(360, location="Lavaridge Town", level=5, npc="Old Woman (Egg)"),
                    entry(374, location="Mossdeep City", level=5, npc="Steven"),
                ],
                "Stationary": [
                    entry(377, location="Desert Ruins", level=40),
                    entry(378, location="Island Cave", level=40),
                    entry(379, location="Ancient Tomb", level=40),
                    entry(380, location="Roaming Hoenn", level=40),
                    entry(381, location="Southern Island", level=50),
                    entry(382, location="Cave of Origin", level=45),
                    entry(383, location="Terra Cave", level=70),
                    entry(384, location="Sky Pillar", level=70),
                ],
            },
            "Pokemon Sapphire": {
                "Starters": [
                    entry(252, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(255, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(258, location="Littleroot Town", level=5, npc="Professor Birch"),
                ],
                "Trades": [
                    entry(273, location="Rustboro City", level=5, npc="School Kid in house"),
                    entry(270, location="Fortree City", level=13, npc="Pokemon Center NPC"),
                    entry(300, location="Pacifidlog Town", level=15, npc="Pokemon Fan in house"),
                    entry(311, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                    entry(312, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                ],
                "Gift": [
                    entry(351, location="Weather Institute", level=25, npc="Scientist"),
                    entry(360, location="Lavaridge Town", level=5, npc="Old Woman (Egg)"),
                    entry(374, location="Mossdeep City", level=5, npc="Steven"),
                ],
                "Stationary": [
                    entry(377, location="Desert Ruins", level=40),
                    entry(378, location="Island Cave", level=40),
                    entry(379, location="Ancient Tomb", level=40),
                    entry(381, location="Roaming Hoenn", level=40),
                    entry(380, location="Southern Island", level=50),
                    entry(382, location="Marine Cave", level=70),
                    entry(383, location="Cave of Origin", level=45),
                    entry(384, location="Sky Pillar", level=70),
                ],
            },
            "Pokemon Emerald": {
                "Starters": [
                    entry(252, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(255, location="Littleroot Town", level=5, npc="Professor Birch"),
                    entry(258, location="Littleroot Town", level=5, npc="Professor Birch"),
                ],
                "Trades": [
                    entry(270, location="Rustboro City", level=5, npc="School Kid in house"),
                    entry(273, location="Fortree City", level=13, npc="Pokemon Center NPC"),
                    entry(300, location="Pacifidlog Town", level=15, npc="Pokemon Fan in house"),
                    entry(311, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                    entry(312, location="Route 110", level=13, npc="Cycling Road gate NPC"),
                ],
                "Gift": [
                    entry(351, location="Weather Institute", level=25, npc="Scientist"),
                    entry(360, location="Lavaridge Town", level=5, npc="Old Woman (Egg)"),
                    entry(374, location="Mossdeep City", level=5, npc="Steven"),
                ],
                "Stationary": [
                    entry(377, location="Desert Ruins", level=40),
                    entry(378, location="Island Cave", level=40),
                    entry(379, location="Ancient Tomb", level=40),
                    entry(380, location="Roaming Hoenn", level=40),
                    entry(381, location="Roaming Hoenn", level=40),
                    entry(382, location="Marine Cave", level=70),
                    entry(383, location="Terra Cave", level=70),
                    entry(384, location="Sky Pillar", level=70),
                ],
            },
            "Pokemon FireRed": {
                "Starters": [
                    entry(1, location="Pallet Town", level=5, npc="Professor Oak"),
                    entry(4, location="Pallet Town", level=5, npc="Professor Oak"),
                    entry(7, location="Pallet Town", level=5, npc="Professor Oak"),
                ],
                "Trades": [
                    entry(122, location="Route 2", level=10, npc="House near Diglett's Cave"),
                    entry(83, location="Vermilion City", level=5, npc="Pokemon Fan Club"),
                    entry(108, location="Cinnabar Island", level=15, npc="Pokemon Lab"),
                    entry(124, location="Cerulean City", level=20, npc="Pokemon Center"),
                    entry(29, location="Route 5", level=16, npc="Underground Path gate"),
                    entry(32, location="Route 11", level=16, npc="Gatehouse"),
                ],
                "Gift": [
                    entry(129, location="Route 4", level=5, npc="Magikarp Salesman"),
                    entry(133, location="Celadon Mansion", level=25, npc="NPC on rooftop"),
                    entry(106, location="Saffron Dojo", level=25, npc="Fighting Dojo Master"),
                    entry(107, location="Saffron Dojo", level=25, npc="Fighting Dojo Master"),
                    entry(131, location="Silph Co.", level=25, npc="Silph Employee"),
                    entry(138, location="Cinnabar Lab", level=5, npc="Scientist (Fossil)"),
                    entry(140, location="Cinnabar Lab", level=5, npc="Scientist (Fossil)"),
                ],
                "Stationary": [
                    entry(143, location="Route 12", level=30),
                    entry(143, location="Route 16", level=30),
                    entry(144, location="Seafoam Islands", level=50),
                    entry(145, location="Power Plant", level=50),
                    entry(146, location="Mt. Ember", level=50),
                    entry(150, location="Cerulean Cave", level=70),
                ],
            },
            "Pokemon LeafGreen": {
                "Starters": [
                    entry(1, location="Pallet Town", level=5, npc="Professor Oak"),
                    entry(4, location="Pallet Town", level=5, npc="Professor Oak"),
                    entry(7, location="Pallet Town", level=5, npc="Professor Oak"),
                ],
                "Trades": [
                    entry(122, location="Route 2", level=10, npc="House near Diglett's Cave"),
                    entry(83, location="Vermilion City", level=5, npc="Pokemon Fan Club"),
                    entry(108, location="Cinnabar Island", level=15, npc="Pokemon Lab"),
                    entry(124, location="Cerulean City", level=20, npc="Pokemon Center"),
                    entry(29, location="Route 5", level=16, npc="Underground Path gate"),
                    entry(32, location="Route 11", level=16, npc="Gatehouse"),
                ],
                "Gift": [
                    entry(129, location="Route 4", level=5, npc="Magikarp Salesman"),
                    entry(133, location="Celadon Mansion", level=25, npc="NPC on rooftop"),
                    entry(106, location="Saffron Dojo", level=25, npc="Fighting Dojo Master"),
                    entry(107, location="Saffron Dojo", level=25, npc="Fighting Dojo Master"),
                    entry(131, location="Silph Co.", level=25, npc="Silph Employee"),
                    entry(138, location="Cinnabar Lab", level=5, npc="Scientist (Fossil)"),
                    entry(140, location="Cinnabar Lab", level=5, npc="Scientist (Fossil)"),
                ],
                "Stationary": [
                    entry(143, location="Route 12", level=30),
                    entry(143, location="Route 16", level=30),
                    entry(144, location="Seafoam Islands", level=50),
                    entry(145, location="Power Plant", level=50),
                    entry(146, location="Mt. Ember", level=50),
                    entry(150, location="Cerulean Cave", level=70),
                ],
            },
        }

        for game_name in self._hunt_game_options:
            categories = data.get(game_name)
            if not isinstance(categories, dict):
                categories = self._default_hunt_soft_reset_categories()

            normalized: Dict[str, List[Dict[str, Any]]] = self._default_hunt_soft_reset_categories()
            for category_name in ("Starters", "Trades", "Gift", "Stationary"):
                raw_entries = categories.get(category_name)
                if isinstance(raw_entries, list):
                    normalized[category_name] = list(raw_entries)

            seen_ids: Set[int] = set()
            all_entries: List[Dict[str, Any]] = []
            for category_name in ("Starters", "Trades", "Gift", "Stationary"):
                for item in normalized.get(category_name, []):
                    if not isinstance(item, dict):
                        continue
                    try:
                        species_id = int(item.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    if species_id <= 0 or species_id in seen_ids:
                        continue
                    seen_ids.add(species_id)
                    all_entries.append(dict(item))
            normalized["Any Soft Reset"] = all_entries
            data[game_name] = normalized

        return data

    def _get_hunt_soft_reset_entries_for_selection(self, game_name: str, category_name: Optional[str] = None) -> List[Dict[str, Any]]:
        category = (category_name or self.hunt_route_var.get()).strip()
        game_data = self._hunt_encounter_catalog.get(game_name, {})
        soft_reset = game_data.get("soft_reset") if isinstance(game_data.get("soft_reset"), dict) else {}

        raw_entries: List[Any] = []
        if category and category in soft_reset:
            candidate = soft_reset.get(category)
            if isinstance(candidate, list):
                raw_entries = candidate
        if not raw_entries:
            candidate = soft_reset.get("Any Soft Reset")
            if isinstance(candidate, list):
                raw_entries = candidate

        allowed_ids = set(self._get_hunt_all_species_ids(game_name))
        seen: Set[int] = set()
        normalized: List[Dict[str, Any]] = []

        for raw in raw_entries:
            payload: Dict[str, Any]
            if isinstance(raw, dict):
                payload = dict(raw)
                try:
                    species_id = int(payload.get("id", payload.get("species_id", 0)))
                except (TypeError, ValueError):
                    continue
            else:
                try:
                    species_id = int(raw)
                except (TypeError, ValueError):
                    continue
                payload = {"id": species_id}

            if species_id <= 0:
                continue
            if allowed_ids and species_id not in allowed_ids:
                continue
            if species_id in seen:
                continue
            seen.add(species_id)

            payload["id"] = species_id
            if isinstance(payload.get("level"), str):
                try:
                    payload["level"] = int(str(payload.get("level")).strip())
                except (TypeError, ValueError):
                    payload.pop("level", None)
            normalized.append(payload)

        return normalized

    def _hunt_location_sort_key(self, value: str) -> Tuple[int, int, str, str]:
        text = str(value or "").strip()
        route_match = re.match(r"^Route\s+(\d+)(?:\s*\(([^)]*)\))?$", text, flags=re.IGNORECASE)
        if route_match:
            variant = str(route_match.group(2) or "").strip().lower()
            return (0, int(route_match.group(1)), variant != "surf", variant)
        return (1, 10_000, False, text.lower())

    def _build_default_hunt_route_options(self) -> Dict[str, List[str]]:
        route_options: Dict[str, List[str]] = {}
        for game_name in self._hunt_game_options:
            entries = self._hunt_encounter_catalog.get(game_name, {}).get("random", {})
            values = sorted(list(entries.keys()), key=self._hunt_location_sort_key)
            if "Any Route / Area" in values:
                values = ["Any Route / Area"] + [v for v in values if v != "Any Route / Area"]
            route_options[game_name] = values or ["Any Route / Area"]
        return route_options

    def _build_default_hunt_fishing_options(self) -> Dict[str, List[str]]:
        fishing_options: Dict[str, List[str]] = {}
        for game_name in self._hunt_game_options:
            entries = self._hunt_encounter_catalog.get(game_name, {}).get("fishing", {})
            values = sorted(list(entries.keys()), key=self._hunt_location_sort_key)
            if "Any Fishing Spot" in values:
                values = ["Any Fishing Spot"] + [v for v in values if v != "Any Fishing Spot"]
            fishing_options[game_name] = values or ["Any Fishing Spot"]
        return fishing_options

    def _get_hunt_route_values(self, game_name: str, mode: str) -> List[str]:
        if mode == "Soft Reset Hunt":
            entries = self._hunt_encounter_catalog.get(game_name, {}).get("soft_reset", {})
            values = list(entries.keys())
            if "Any Soft Reset" in values:
                values = ["Any Soft Reset"] + [v for v in values if v != "Any Soft Reset"]
            return values or ["Any Soft Reset"]

        if mode == "Fishing Encounter Hunt":
            return list(self._hunt_fishing_options.get(game_name, ["Any Fishing Spot"]))

        if mode == "Wild Encounter Hunt":
            return list(self._hunt_route_options.get(game_name, ["Any Route / Area"]))

        return []

    def _get_hunt_all_species_ids(self, game_name: str) -> List[int]:
        reader = self.tracker.pokemon_reader if self.tracker else None
        if not reader:
            return []
        config = reader.get_game_config(game_name) if game_name else None
        try:
            max_pokemon = int(config.get("max_pokemon", 386)) if isinstance(config, dict) else 386
        except (TypeError, ValueError):
            max_pokemon = 386
        return [pid for pid in range(1, max_pokemon + 1) if isinstance(reader.POKEMON_NAMES.get(pid), str)]

    def _normalize_hunt_species_ids_for_game(self, game_name: str, species_ids: List[int]) -> List[int]:
        allowed = set(self._get_hunt_all_species_ids(game_name))
        ordered: List[int] = []
        seen: Set[int] = set()
        for raw in species_ids:
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid <= 0 or pid not in allowed or pid in seen:
                continue
            ordered.append(pid)
            seen.add(pid)
        return ordered

    def _get_hunt_species_ids_for_selection(self, game_name: str, mode: Optional[str] = None, route_name: Optional[str] = None) -> List[int]:
        mode_value = (mode or self.hunt_mode_var.get()).strip()
        route_value = (route_name or self.hunt_route_var.get()).strip()
        game_data = self._hunt_encounter_catalog.get(game_name, {})

        if mode_value == "Soft Reset Hunt":
            entries = self._get_hunt_soft_reset_entries_for_selection(game_name, route_value)
            species_ids: List[int] = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                try:
                    pid = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if pid > 0:
                    species_ids.append(pid)
            normalized = self._normalize_hunt_species_ids_for_game(game_name, species_ids)
            return normalized or self._get_hunt_all_species_ids(game_name)

        if mode_value == "Wild Encounter Hunt":
            entries = game_data.get("random", {})
            if route_value and route_value in entries:
                species_ids = list(entries.get(route_value, []))
            elif "Any Route / Area" in entries:
                species_ids = list(entries.get("Any Route / Area", []))
            else:
                species_ids = [pid for values in entries.values() for pid in values]
            normalized = self._normalize_hunt_species_ids_for_game(game_name, species_ids)
            return normalized or self._get_hunt_all_species_ids(game_name)

        if mode_value == "Fishing Encounter Hunt":
            entries = game_data.get("fishing", {})
            if route_value and route_value in entries:
                species_ids = list(entries.get(route_value, []))
            elif "Any Fishing Spot" in entries:
                species_ids = list(entries.get("Any Fishing Spot", []))
            else:
                species_ids = [pid for values in entries.values() for pid in values]
            normalized = self._normalize_hunt_species_ids_for_game(game_name, species_ids)
            return normalized or self._get_hunt_all_species_ids(game_name)

        # Hatching Egg Hunt fallback pool.
        return self._get_hunt_all_species_ids(game_name)

    def _get_hunt_other_species_ids(self, game_name: str) -> List[int]:
        mode = self.hunt_mode_var.get().strip()
        if mode == "Hatching Egg Hunt":
            return []
        if mode == "Soft Reset Hunt":
            entries = self._get_hunt_soft_reset_entries_for_selection(game_name)
            ids: List[int] = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                try:
                    pid = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if pid > 0:
                    ids.append(pid)
            return ids
        return self._get_hunt_species_ids_for_selection(game_name)

    def _build_hunt_tab(self):
        """Build shiny hunt tracker tab."""
        container = ttk.Frame(self.hunt_frame, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        controls = ttk.LabelFrame(container, text="Hunt Setup", padding=10)
        controls.pack(fill=tk.X, pady=(0, 10))
        for col in range(8):
            controls.columnconfigure(col, weight=1)

        ttk.Label(controls, text="Mode:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._hunt_mode_combo = ttk.Combobox(
            controls,
            textvariable=self.hunt_mode_var,
            values=self._hunt_modes,
            state="readonly",
            width=24,
        )
        self._hunt_mode_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._hunt_mode_combo.bind("<<ComboboxSelected>>", self._on_hunt_mode_selected)

        ttk.Label(controls, text="Game:").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self._hunt_game_combo = ttk.Combobox(
            controls,
            textvariable=self.hunt_game_var,
            values=self._hunt_game_options,
            state="readonly",
            width=18,
        )
        self._hunt_game_combo.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        self._hunt_game_combo.bind("<<ComboboxSelected>>", self._on_hunt_game_selected)

        self._hunt_route_label = ttk.Label(controls, text="Route:")
        self._hunt_route_label.grid(row=0, column=4, sticky="w", padx=4, pady=4)
        self._hunt_route_combo = ttk.Combobox(
            controls,
            textvariable=self.hunt_route_var,
            values=["Any Route / Area"],
            state="readonly",
            width=24,
        )
        self._hunt_route_combo.grid(row=0, column=5, sticky="ew", padx=4, pady=4)
        self._hunt_route_combo.bind("<<ComboboxSelected>>", self._on_hunt_route_selected)

        ttk.Label(controls, text="Target:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self._hunt_target_combo = ttk.Combobox(
            controls,
            textvariable=self.hunt_target_var,
            values=[],
            state="readonly",
            width=36,
        )
        self._hunt_target_combo.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        self._hunt_target_combo.bind("<<ComboboxSelected>>", self._on_hunt_target_selected)

        self._hunt_start_btn = ttk.Button(controls, text="Start Hunt", command=self._start_hunt)
        self._hunt_start_btn.grid(row=1, column=4, sticky="ew", padx=4, pady=4)

        self._hunt_pause_btn = ttk.Button(controls, text="Pause Hunt", command=self._pause_hunt, state="disabled")
        self._hunt_pause_btn.grid(row=1, column=5, sticky="ew", padx=4, pady=4)

        ttk.Button(controls, text="Reset Counter", command=self._reset_hunt_counter).grid(
            row=1, column=6, sticky="ew", padx=4, pady=4
        )

        target_frame = ttk.LabelFrame(container, text="Target", padding=10)
        target_frame.pack(fill=tk.X, pady=(0, 10))

        target_inner = ttk.Frame(target_frame)
        target_inner.pack(anchor=tk.CENTER)

        self._hunt_target_name_label = ttk.Label(
            target_inner,
            text="No target selected",
            font=("Segoe UI", 12, "bold"),
            anchor="center",
            justify=tk.CENTER,
        )
        self._hunt_target_name_label.pack(pady=(0, 6))

        self._hunt_target_sprite_label = ttk.Label(target_inner, text="Sprite loading...")
        self._hunt_target_sprite_label.pack(pady=(0, 6))

        self._hunt_target_type_frame = ttk.Frame(target_inner)
        self._hunt_target_type_frame.pack(anchor=tk.CENTER, pady=(0, 4))
        self._hunt_target_type_labels = []
        for _ in range(2):
            type_label = ttk.Label(self._hunt_target_type_frame, text="")
            type_label.pack(side=tk.LEFT, padx=2)
            self._hunt_target_type_labels.append(type_label)

        self._hunt_target_meta_label = ttk.Label(
            target_inner,
            text="",
            style="Subtle.TLabel",
            anchor="center",
            justify=tk.CENTER,
            wraplength=520,
        )
        self._hunt_target_meta_label.pack(pady=(0, 6))

        counter_row = ttk.Frame(target_inner)
        counter_row.pack()

        self._hunt_counter_label = ttk.Label(
            counter_row,
            text="Encounters: 0",
            font=("Segoe UI", 12, "bold"),
            anchor="center",
            justify=tk.CENTER,
        )
        self._hunt_counter_label.pack(side=tk.LEFT, padx=(0, 10))

        self._hunt_phase_label = ttk.Label(
            counter_row,
            text="Phases: 0",
            font=("Segoe UI", 12, "bold"),
            anchor="center",
            justify=tk.CENTER,
        )
        self._hunt_phase_label.pack(side=tk.LEFT, padx=(10, 0))

        self._hunt_mode_hint_label = ttk.Label(
            target_inner,
            text="",
            style="Subtle.TLabel",
            anchor="center",
            justify=tk.CENTER,
        )
        self._hunt_mode_hint_label.pack(pady=(6, 0))

        available_frame = ttk.LabelFrame(container, text="Available Pokemon", padding=10)
        available_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        available_body = ttk.Frame(available_frame)
        available_body.pack(fill=tk.BOTH, expand=True)

        self._hunt_available_canvas = tk.Canvas(available_body, highlightthickness=0, height=320)
        self._hunt_available_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._hunt_available_scrollbar = ttk.Scrollbar(available_body, orient=tk.VERTICAL, command=self._hunt_available_canvas.yview)
        self._hunt_available_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._hunt_available_canvas.configure(yscrollcommand=self._hunt_available_scrollbar.set)

        self._hunt_other_sprites_frame = ttk.Frame(self._hunt_available_canvas)
        self._hunt_available_window_id = self._hunt_available_canvas.create_window((0, 0), window=self._hunt_other_sprites_frame, anchor="nw")
        self._hunt_other_sprites_frame.bind("<Configure>", self._on_hunt_available_frame_configure)
        self._hunt_available_canvas.bind("<Configure>", self._on_hunt_available_canvas_configure)
        self._hunt_available_canvas.bind("<MouseWheel>", self._on_hunt_available_mousewheel)
        self._hunt_other_sprites_frame.bind("<MouseWheel>", self._on_hunt_available_mousewheel)
        self._hunt_other_sprite_labels = []

        self.hunt_status_label = ttk.Label(container, text="Hunt idle", style="Subtle.TLabel")
        self.hunt_status_label.pack(anchor=tk.W)

        self._update_hunt_mode_controls()
        self._load_last_hunt_for_game(self.hunt_game_var.get().strip(), auto_start=False)

    def _get_hunt_species_options(self, game_name: str) -> List[Tuple[int, str]]:
        reader = self.tracker.pokemon_reader if self.tracker else None
        if not reader:
            return []

        species_ids = self._get_hunt_species_ids_for_selection(game_name)
        options: List[Tuple[int, str]] = []
        for pid in species_ids:
            name = reader.POKEMON_NAMES.get(pid)
            if isinstance(name, str) and name.strip():
                options.append((int(pid), name.strip()))
        return options

    def _on_hunt_mode_selected(self, _event=None):
        keep_active = bool(self._hunt_active)
        self._update_hunt_mode_controls()
        self._load_saved_hunt_for_current_selection(auto_start=keep_active)
        if keep_active and not self._hunt_active:
            self._start_hunt(silent=True, emit_log=False, persist=True)

    def _on_hunt_game_selected(self, _event=None):
        keep_active = bool(self._hunt_active)
        selected_game = self.hunt_game_var.get().strip()
        self._load_last_hunt_for_game(selected_game, auto_start=keep_active)
        if keep_active and not self._hunt_active:
            self._start_hunt(silent=True, emit_log=False, persist=True)

    def _on_hunt_route_selected(self, _event=None):
        keep_active = bool(self._hunt_active)
        self._refresh_hunt_targets()
        self._load_saved_hunt_for_current_selection(auto_start=keep_active)
        if keep_active and not self._hunt_active:
            self._start_hunt(silent=True, emit_log=False, persist=True)

    def _on_hunt_target_selected(self, _event=None):
        keep_active = bool(self._hunt_active)
        self._update_hunt_target_display()
        self._load_saved_hunt_for_current_selection(auto_start=keep_active)
        if keep_active and not self._hunt_active:
            self._start_hunt(silent=True, emit_log=False, persist=True)

    def _capture_current_hunt_profile(self) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        game_name = self.hunt_game_var.get().strip() or (self.tracker.game_name or "")
        if game_name not in self._hunt_game_options:
            return None

        mode = self.hunt_mode_var.get().strip()
        route_name = self.hunt_route_var.get().strip()
        target_id = self._get_hunt_target_pokemon_id()
        profile_key = self._build_hunt_profile_key(mode, route_name, target_id)
        profile: Dict[str, Any] = {
            "mode": mode,
            "route": route_name,
            "target_id": target_id,
            "counter": int(max(0, self._hunt_counter)),
            "phase_count": int(max(0, self._hunt_phase_count)),
            "species_counts": {str(int(pid)): int(max(0, count)) for pid, count in self._hunt_species_counts.items() if int(count) > 0},
            "active": bool(self._hunt_active),
            "updated_at": int(time.time()),
        }
        return game_name, profile_key, profile

    def _save_current_hunt_profile(self, *, active_override: Optional[bool] = None, set_last_profile_key: bool = True):
        if self._hunt_profile_applying:
            return

        captured = self._capture_current_hunt_profile()
        if not captured:
            return

        game_name, profile_key, profile = captured
        if active_override is not None:
            profile["active"] = bool(active_override)

        game_store = self._get_hunt_profile_store_for_game(game_name, create=True)
        if not isinstance(game_store, dict):
            return

        profiles = game_store.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
            game_store["profiles"] = profiles

        if bool(profile.get("active")):
            for existing in profiles.values():
                if isinstance(existing, dict):
                    existing["active"] = False

        profiles[profile_key] = profile
        if set_last_profile_key:
            game_store["last_profile_key"] = profile_key
        self._save_hunt_profiles()

    def _resolve_hunt_target_display(self, game_name: str, target_id: int) -> str:
        if int(target_id or 0) <= 0:
            return ""
        for pid, name in self._get_hunt_species_options(game_name):
            if int(pid) == int(target_id):
                return f"{int(pid):03d} {name}"
        return ""

    def _apply_hunt_profile(self, game_name: str, profile: Dict[str, Any], *, auto_start: bool):
        if game_name not in self._hunt_game_options or not isinstance(profile, dict):
            return

        profile_mode = str(profile.get("mode") or "").strip()
        if profile_mode not in self._hunt_modes:
            profile_mode = self._hunt_modes[0]

        route_name = str(profile.get("route") or "").strip()
        try:
            target_id = int(profile.get("target_id", 0))
        except (TypeError, ValueError):
            target_id = 0
        try:
            counter_value = int(profile.get("counter", 0))
        except (TypeError, ValueError):
            counter_value = 0
        try:
            phase_value = int(profile.get("phase_count", 0))
        except (TypeError, ValueError):
            phase_value = 0
        profile_active = bool(profile.get("active", False))
        species_counts_raw = profile.get("species_counts")
        parsed_species_counts: Dict[int, int] = {}
        if isinstance(species_counts_raw, dict):
            for raw_pid, raw_count in species_counts_raw.items():
                try:
                    pid_int = int(raw_pid)
                    count_int = int(raw_count)
                except (TypeError, ValueError):
                    continue
                if pid_int > 0 and count_int > 0:
                    parsed_species_counts[pid_int] = count_int

        self._hunt_profile_applying = True
        try:
            if self.hunt_game_var.get().strip() != game_name:
                self.hunt_game_var.set(game_name)

            self.hunt_mode_var.set(profile_mode)
            self._update_hunt_mode_controls()

            route_values = self._get_hunt_route_values(game_name, profile_mode)
            if route_name and route_name in route_values:
                self.hunt_route_var.set(route_name)
            elif route_values:
                self.hunt_route_var.set(route_values[0])
            else:
                self.hunt_route_var.set("")

            self._refresh_hunt_targets()

            target_display = self._resolve_hunt_target_display(game_name, target_id)
            if target_display:
                self.hunt_target_var.set(target_display)
            self._hunt_species_counts = dict(parsed_species_counts)
            self._update_hunt_target_display()
            self._set_hunt_counter(counter_value)
            self._set_hunt_phase_count(phase_value)
        finally:
            self._hunt_profile_applying = False

        if auto_start:
            started = self._start_hunt(silent=True, emit_log=False, persist=False)
            if not started:
                self._pause_hunt(emit_log=False, persist=False)
                log_event(
                    logging.WARNING,
                    "hunt_auto_start_failed",
                    game=game_name,
                    mode=profile_mode,
                    route=self.hunt_route_var.get().strip(),
                    target=self.hunt_target_var.get().strip(),
                    profile_active=bool(profile_active),
                )
        else:
            self._pause_hunt(emit_log=False, persist=False)

    def _load_saved_hunt_for_current_selection(self, *, auto_start: bool = False) -> bool:
        game_name = self.hunt_game_var.get().strip() or (self.tracker.game_name or "")
        if game_name not in self._hunt_game_options:
            return False

        game_store = self._get_hunt_profile_store_for_game(game_name, create=False)
        profiles = game_store.get("profiles") if isinstance(game_store, dict) else None
        if not isinstance(profiles, dict):
            profiles = {}

        profile_key = self._build_hunt_profile_key(
            self.hunt_mode_var.get().strip(),
            self.hunt_route_var.get().strip(),
            self._get_hunt_target_pokemon_id(),
        )
        profile = profiles.get(profile_key)
        if isinstance(profile, dict):
            self._apply_hunt_profile(game_name, profile, auto_start=auto_start)
            if isinstance(game_store, dict):
                game_store["last_profile_key"] = profile_key
                self._save_hunt_profiles()
            return True

        self._hunt_profile_applying = True
        try:
            self._hunt_species_counts = {}
            self._set_hunt_counter(0)
            self._set_hunt_phase_count(0)
        finally:
            self._hunt_profile_applying = False

        self._update_hunt_other_species_display()
        self._pause_hunt(emit_log=False, persist=False)
        self._save_current_hunt_profile(active_override=False, set_last_profile_key=False)
        return False

    def _load_last_hunt_for_game(self, game_name: str, *, auto_start: bool):
        game_key = (game_name or "").strip()
        if game_key not in self._hunt_game_options:
            self._refresh_hunt_targets()
            self._hunt_profile_applying = True
            try:
                self._hunt_species_counts = {}
                self._set_hunt_counter(0)
                self._set_hunt_phase_count(0)
            finally:
                self._hunt_profile_applying = False
            self._update_hunt_other_species_display()
            self._pause_hunt(emit_log=False, persist=False)
            return

        if self.hunt_game_var.get().strip() != game_key:
            self.hunt_game_var.set(game_key)

        game_store = self._get_hunt_profile_store_for_game(game_key, create=False)
        profiles = game_store.get("profiles") if isinstance(game_store, dict) else None
        if not isinstance(profiles, dict):
            profiles = {}

        profile: Optional[Dict[str, Any]] = None
        if auto_start and profiles:
            active_profiles = sorted(
                (
                    item
                    for item in profiles.values()
                    if isinstance(item, dict) and bool(item.get("active", False))
                ),
                key=lambda item: int(item.get("updated_at", 0)) if isinstance(item.get("updated_at", 0), int) else 0,
                reverse=True,
            )
            if active_profiles:
                profile = active_profiles[0]

        if profile is None:
            last_key = game_store.get("last_profile_key") if isinstance(game_store, dict) else ""
            if isinstance(last_key, str) and last_key:
                candidate = profiles.get(last_key)
                if isinstance(candidate, dict):
                    profile = candidate

        if profile is None and profiles:
            sorted_profiles = sorted(
                (item for item in profiles.values() if isinstance(item, dict)),
                key=lambda item: int(item.get("updated_at", 0)) if isinstance(item.get("updated_at", 0), int) else 0,
                reverse=True,
            )
            if sorted_profiles:
                profile = sorted_profiles[0]

        if isinstance(profile, dict):
            self._apply_hunt_profile(game_key, profile, auto_start=auto_start)
            self._save_current_hunt_profile(active_override=bool(profile.get("active", False)))
            return

        self._update_hunt_mode_controls()
        self._hunt_profile_applying = True
        try:
            self._hunt_species_counts = {}
            self._set_hunt_counter(0)
            self._set_hunt_phase_count(0)
        finally:
            self._hunt_profile_applying = False
        self._update_hunt_other_species_display()
        self._pause_hunt(emit_log=False, persist=False)
        self._save_current_hunt_profile(active_override=False, set_last_profile_key=False)

    def _refresh_hunt_targets(self, _event=None):
        game_name = self.hunt_game_var.get().strip()
        if not game_name and self._hunt_game_options:
            game_name = self._hunt_game_options[0]
            self.hunt_game_var.set(game_name)

        mode = self.hunt_mode_var.get().strip()
        route_values = self._get_hunt_route_values(game_name, mode)
        if self._hunt_route_combo is not None:
            self._hunt_route_combo.configure(values=route_values)
            current_route = self.hunt_route_var.get().strip()
            if current_route not in route_values:
                self.hunt_route_var.set(route_values[0] if route_values else "")

        species_options = self._get_hunt_species_options(game_name)
        display_values = [f"{pid:03d} {name}" for pid, name in species_options]
        if self._hunt_target_combo is not None:
            self._hunt_target_combo.configure(values=display_values)

        current_target = self.hunt_target_var.get().strip()
        if current_target not in display_values:
            self.hunt_target_var.set(display_values[0] if display_values else "")

        self._update_hunt_target_display()

    def _get_hunt_target_pokemon_id(self) -> int:
        raw = self.hunt_target_var.get().strip()
        if not raw:
            return 0
        token = raw.split(" ", 1)[0].strip()
        try:
            return int(token)
        except (TypeError, ValueError):
            return 0

    def _set_hunt_counter(self, value: int):
        self._hunt_counter = max(0, int(value))
        if isinstance(self._hunt_counter_label, ttk.Label):
            self._hunt_counter_label.configure(text=f"Encounters: {self._hunt_counter:,}")
        if not self._hunt_profile_applying:
            self._save_current_hunt_profile()

    def _set_hunt_phase_count(self, value: int):
        self._hunt_phase_count = max(0, int(value))
        if isinstance(self._hunt_phase_label, ttk.Label):
            self._hunt_phase_label.configure(text=f"Phases: {self._hunt_phase_count:,}")
        if not self._hunt_profile_applying:
            self._save_current_hunt_profile()

    def _get_hunt_species_count(self, species_id: int) -> int:
        try:
            key = int(species_id)
        except (TypeError, ValueError):
            return 0
        if key <= 0:
            return 0
        return int(self._hunt_species_counts.get(key, 0))

    def _record_hunt_species_encounter(self, species_id: int):
        try:
            key = int(species_id)
        except (TypeError, ValueError):
            return
        if key <= 0:
            return
        self._hunt_species_counts[key] = self._get_hunt_species_count(key) + 1
        label = self._hunt_species_count_labels.get(key)
        if isinstance(label, ttk.Label):
            label.configure(text=f"Encounters: {self._hunt_species_counts[key]:,}")

    def _update_hunt_target_display(self, _event=None):
        target_id = self._get_hunt_target_pokemon_id()
        game_name = self.hunt_game_var.get().strip() or (self.tracker.game_name or "")
        target_name = self.tracker.pokemon_reader.get_pokemon_name(target_id) if target_id > 0 and self.tracker and self.tracker.pokemon_reader else "No target selected"

        if isinstance(self._hunt_target_name_label, ttk.Label):
            if target_id > 0:
                self._hunt_target_name_label.configure(text=f"Target: {target_name} (#{target_id})")
            else:
                self._hunt_target_name_label.configure(text="No target selected")

        if isinstance(self._hunt_target_sprite_label, ttk.Label):
            if target_id > 0:
                sprite = self._request_party_sprite(target_id, game_name, shiny=True)
                if sprite is not None:
                    self._hunt_target_sprite_label.configure(image=sprite, text="")
                    setattr(self._hunt_target_sprite_label, "image", sprite)
                else:
                    self._hunt_target_sprite_label.configure(image="", text="Sprite loading...")
                    setattr(self._hunt_target_sprite_label, "image", None)
            else:
                self._hunt_target_sprite_label.configure(image="", text="No target")
                setattr(self._hunt_target_sprite_label, "image", None)

        target_types: List[str] = []
        target_details: List[str] = []
        context_details: List[str] = []
        mode = self.hunt_mode_var.get().strip()
        route_value = self.hunt_route_var.get().strip()
        target_entry: Optional[Dict[str, Any]] = None

        if target_id > 0 and mode == "Soft Reset Hunt":
            for item in self._get_hunt_soft_reset_entries_for_selection(game_name):
                if not isinstance(item, dict):
                    continue
                try:
                    if int(item.get("id", 0)) == int(target_id):
                        target_entry = item
                        break
                except (TypeError, ValueError):
                    continue

        if isinstance(target_entry, dict):
            raw_types = target_entry.get("types")
            if isinstance(raw_types, list):
                for value in raw_types:
                    if isinstance(value, str) and value.strip():
                        target_types.append(value.strip().lower())

            location = target_entry.get("location")
            if isinstance(location, str) and location.strip():
                target_details.append(location.strip())
            level = target_entry.get("level")
            if isinstance(level, int) and level > 0:
                target_details.append(f"Lv.{level}")
            npc = target_entry.get("npc")
            if isinstance(npc, str) and npc.strip():
                target_details.append(f"NPC: {npc.strip()}")

        if target_id > 0 and not target_types:
            resolved_types = self._request_species_types(target_id, game_name)
            if isinstance(resolved_types, list):
                for value in resolved_types:
                    if isinstance(value, str) and value.strip():
                        target_types.append(value.strip().lower())

        if mode == "Wild Encounter Hunt" and route_value:
            context_details.append(f"Route: {route_value}")
        elif mode == "Fishing Encounter Hunt" and route_value:
            context_details.append(f"Fishing Spot: {route_value}")
        elif mode == "Soft Reset Hunt" and route_value:
            context_details.append(f"Category: {route_value}")
        elif mode == "Hatching Egg Hunt":
            context_details.append("Egg Hunt")

        target_types = target_types[:2]

        labels = self._hunt_target_type_labels if isinstance(self._hunt_target_type_labels, list) else []
        for idx, type_label in enumerate(labels):
            if not isinstance(type_label, ttk.Label):
                continue
            if idx < len(target_types):
                type_name = target_types[idx]
                icon = self._request_party_type_icon(type_name, game_name)
                if icon is not None:
                    type_label.configure(image=icon, text="")
                    setattr(type_label, "image", icon)
                else:
                    type_label.configure(image="", text=type_name.title())
                    setattr(type_label, "image", None)
            else:
                type_label.configure(image="", text="")
                setattr(type_label, "image", None)

        if isinstance(self._hunt_target_meta_label, ttk.Label):
            meta_parts = context_details + target_details
            if meta_parts:
                self._hunt_target_meta_label.configure(text=" / ".join(meta_parts))
            else:
                self._hunt_target_meta_label.configure(text="")

        self._update_hunt_other_species_display()

    def _update_hunt_mode_controls(self, _event=None):
        mode = self.hunt_mode_var.get().strip()

        if mode == "Soft Reset Hunt":
            route_enabled = True
            route_label = "Category:"
        elif mode == "Fishing Encounter Hunt":
            route_enabled = True
            route_label = "Fishing Spot:"
        elif mode == "Wild Encounter Hunt":
            route_enabled = True
            route_label = "Route:"
        else:
            route_enabled = False
            route_label = "Route:"

        if isinstance(self._hunt_route_label, ttk.Label):
            self._hunt_route_label.configure(text=route_label)

        if isinstance(self._hunt_route_combo, ttk.Combobox):
            self._hunt_route_combo.configure(state="readonly" if route_enabled else "disabled")

        if isinstance(self._hunt_mode_hint_label, ttk.Label):
            hints = {
                "Soft Reset Hunt": "Choose category + target. Available Pokemon shows event cards.",
                "Wild Encounter Hunt": "Choose route + target. Target list is filtered to that route.",
                "Fishing Encounter Hunt": "Choose fishing spot + target. Target list is filtered to that fishing spot.",
                "Hatching Egg Hunt": "Choose target species. Counter increments when eggs hatch into that target.",
            }
            self._hunt_mode_hint_label.configure(text=hints.get(mode, ""))

        self._refresh_hunt_targets()

    def _update_hunt_other_species_display(self):
        if not isinstance(self._hunt_other_sprites_frame, ttk.Frame):
            return

        for child in self._hunt_other_sprites_frame.winfo_children():
            child.destroy()
        self._hunt_species_count_labels = {}

        game_name = self.hunt_game_var.get().strip() or (self.tracker.game_name or "")
        mode = self.hunt_mode_var.get().strip()

        if mode == "Soft Reset Hunt":
            entries = self._get_hunt_soft_reset_entries_for_selection(game_name)
            if not entries:
                ttk.Label(self._hunt_other_sprites_frame, text="No available Pokemon for this category.", style="Subtle.TLabel").pack(anchor=tk.W)
                self._on_hunt_available_frame_configure()
                return

            columns = 3
            for col in range(columns):
                self._hunt_other_sprites_frame.columnconfigure(col, weight=1)

            for idx, item in enumerate(entries):
                try:
                    pid = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if pid <= 0:
                    continue

                name = self._get_pokemon_name(pid)
                card = ttk.LabelFrame(self._hunt_other_sprites_frame, text=f"#{pid:03d} {name}", padding=6)
                card.grid(row=idx // columns, column=idx % columns, sticky="nsew", padx=4, pady=4)

                sprite = self._request_party_sprite(pid, game_name, shiny=False)
                sprite_label = ttk.Label(card, text="Sprite loading...", anchor=tk.CENTER, justify=tk.CENTER)
                if sprite is not None:
                    sprite_label.configure(image=sprite, text="")
                    setattr(sprite_label, "image", sprite)
                sprite_label.pack(anchor=tk.CENTER, pady=(0, 4))

                type_row = ttk.Frame(card)
                type_row.pack(anchor=tk.CENTER, pady=(0, 4))

                types: List[str] = []
                raw_types = item.get("types")
                if isinstance(raw_types, list):
                    for value in raw_types:
                        if isinstance(value, str) and value.strip():
                            types.append(value.strip().lower())
                if not types:
                    resolved_types = self._request_species_types(pid, game_name)
                    if isinstance(resolved_types, list):
                        for value in resolved_types:
                            if isinstance(value, str) and value.strip():
                                types.append(value.strip().lower())
                types = types[:2]

                if types:
                    for type_name in types:
                        icon = self._request_party_type_icon(type_name, game_name)
                        icon_label = ttk.Label(type_row, text="")
                        if icon is not None:
                            icon_label.configure(image=icon)
                            setattr(icon_label, "image", icon)
                        else:
                            icon_label.configure(text=type_name.title())
                        icon_label.pack(side=tk.LEFT, padx=2)

                count_label = ttk.Label(card, text=f"Encounters: {self._get_hunt_species_count(pid):,}", style="Subtle.TLabel")
                count_label.pack(anchor=tk.CENTER, pady=(0, 4))
                self._hunt_species_count_labels[int(pid)] = count_label

                details: List[str] = []
                location = item.get("location")
                if isinstance(location, str) and location.strip():
                    details.append(location.strip())
                level = item.get("level")
                if isinstance(level, int) and level > 0:
                    details.append(f"Lv.{level}")
                npc = item.get("npc")
                if isinstance(npc, str) and npc.strip():
                    details.append(f"NPC: {npc.strip()}")

                if details:
                    ttk.Label(card, text=" / ".join(details), wraplength=200, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

            self._on_hunt_available_frame_configure()
            return

        species_ids = self._get_hunt_other_species_ids(game_name)
        if not species_ids:
            ttk.Label(self._hunt_other_sprites_frame, text="No available Pokemon for this selection.", style="Subtle.TLabel").pack(anchor=tk.W)
            self._on_hunt_available_frame_configure()
            return

        columns = 8
        for col in range(columns):
            self._hunt_other_sprites_frame.columnconfigure(col, weight=1)

        for idx, pid in enumerate(species_ids):
            item_frame = ttk.Frame(self._hunt_other_sprites_frame)
            item_frame.grid(row=idx // columns, column=idx % columns, padx=4, pady=4, sticky="n")

            sprite = self._request_party_sprite(int(pid), game_name, shiny=False)
            sprite_label = ttk.Label(item_frame, text="...", anchor=tk.CENTER, justify=tk.CENTER)
            if sprite is not None:
                sprite_label.configure(image=sprite, text="")
                setattr(sprite_label, "image", sprite)
            sprite_label.pack(anchor=tk.CENTER)

            ttk.Label(item_frame, text=self._get_pokemon_name(int(pid)), wraplength=100, justify=tk.CENTER).pack(anchor=tk.CENTER)
            count_label = ttk.Label(item_frame, text=f"Encounters: {self._get_hunt_species_count(int(pid)):,}", style="Subtle.TLabel", justify=tk.CENTER)
            count_label.pack(anchor=tk.CENTER)
            self._hunt_species_count_labels[int(pid)] = count_label

        self._on_hunt_available_frame_configure()

    def _on_hunt_available_frame_configure(self, _event=None):
        if not isinstance(self._hunt_available_canvas, tk.Canvas):
            return
        bbox = self._hunt_available_canvas.bbox("all")
        if bbox:
            self._hunt_available_canvas.configure(scrollregion=bbox)

    def _on_hunt_available_canvas_configure(self, event):
        if not isinstance(self._hunt_available_canvas, tk.Canvas):
            return
        if self._hunt_available_window_id is not None:
            self._hunt_available_canvas.itemconfigure(self._hunt_available_window_id, width=event.width)

    def _on_hunt_available_mousewheel(self, event):
        if not isinstance(self._hunt_available_canvas, tk.Canvas):
            return
        delta = 0
        raw_delta = getattr(event, "delta", 0)
        if raw_delta:
            delta = -int(raw_delta / 120)
        else:
            num = getattr(event, "num", None)
            if num == 4:
                delta = -1
            elif num == 5:
                delta = 1
        if delta != 0:
            self._hunt_available_canvas.yview_scroll(delta, "units")

    def _prime_hunt_baseline(self):
        """Prime encounter/party baseline so counters start from next new event."""
        mode = self.hunt_mode_var.get().strip()
        game_for_hunt = self.hunt_game_var.get().strip() or (self.tracker.game_name if self.tracker else "") or ""
        self._hunt_last_party_snapshot = self._snapshot_party_for_hunt(self.tracker._last_party if self.tracker else [])
        self._hunt_last_enemy_signature = None
        self._hunt_last_enemy_seen_at = 0.0
        self._hunt_last_raw_log_key = None
        self._hunt_last_raw_none_log_at = 0.0
        self._hunt_last_target_signature = None
        self._hunt_enemy_present = False
        self._hunt_target_present = False
        self._hunt_soft_reset_reset_pending = False
        self._hunt_soft_reset_seen_in_pokedex = False
        self._hunt_soft_reset_target_id = 0

        if mode == "Hatching Egg Hunt":
            self._hunt_initialized = True
            return

        if mode in {"Wild Encounter Hunt", "Fishing Encounter Hunt"}:
            # Count the next observed battle as an encounter, even when hunt starts mid-battle.
            self._hunt_initialized = True
            return

        encounter = self.tracker.pokemon_reader.read_wild_encounter(game_for_hunt) if self.tracker and self.tracker.pokemon_reader else None
        if isinstance(encounter, dict):
            signature = str(encounter.get("signature", "")).strip()
            if signature:
                self._hunt_last_enemy_signature = signature
            self._hunt_enemy_present = bool(encounter.get("is_wild", True))
            self._hunt_last_enemy_seen_at = time.monotonic()

        if mode == "Soft Reset Hunt":
            present, target_signature, _, _, _ = self._get_soft_reset_target_state(encounter, game_for_hunt)
            self._hunt_target_present = bool(present)
            self._hunt_last_target_signature = str(target_signature).strip() if isinstance(target_signature, str) and str(target_signature).strip() else None
            self._hunt_soft_reset_seen_in_pokedex = self._is_hunt_target_in_pokedex()
            self._hunt_soft_reset_target_id = self._get_hunt_target_pokemon_id()

        self._hunt_initialized = True

    def _start_hunt(self, *, silent: bool = False, emit_log: bool = True, persist: bool = True) -> bool:
        game_name = self.hunt_game_var.get().strip()
        if game_name not in self._hunt_game_options:
            if not silent:
                messagebox.showwarning("Unsupported Game", "Shiny Hunt supports Gen 2/3 games only.")
            return False

        if self.hunt_mode_var.get().strip() != "Hatching Egg Hunt" and self._get_hunt_target_pokemon_id() <= 0:
            if not silent:
                messagebox.showwarning("No Target", "Select a hunt target before starting.")
            return False

        self._hunt_active = True
        self._hunt_alerted_signatures = set()
        self._hunt_last_waiting_state = bool(self.retroarch.is_waiting_for_launch())
        self._hunt_soft_reset_reset_pending = False
        self._hunt_recent_other_species.clear()
        self._update_hunt_other_species_display()
        self._prime_hunt_baseline()
        if isinstance(self._hunt_start_btn, ttk.Button):
            self._hunt_start_btn.configure(state="disabled")
        if isinstance(self._hunt_pause_btn, ttk.Button):
            self._hunt_pause_btn.configure(state="normal")
        if isinstance(self.hunt_status_label, ttk.Label):
            self.hunt_status_label.configure(text="Hunt active")
        if emit_log:
            self._log(f"[HUNT] Started {self.hunt_mode_var.get()}", "info")
        if persist and not self._hunt_profile_applying:
            self._save_current_hunt_profile(active_override=True)
        return True

    def _pause_hunt(self, emit_log: bool = True, persist: bool = True):
        self._hunt_active = False
        if isinstance(self._hunt_start_btn, ttk.Button):
            self._hunt_start_btn.configure(state="normal")
        if isinstance(self._hunt_pause_btn, ttk.Button):
            self._hunt_pause_btn.configure(state="disabled")
        if isinstance(self.hunt_status_label, ttk.Label):
            self.hunt_status_label.configure(text="Hunt paused")
        if emit_log:
            self._log("[HUNT] Hunt paused", "info")
        if persist and not self._hunt_profile_applying:
            self._save_current_hunt_profile(active_override=False)

    def _reset_hunt_counter(self, emit_log: bool = True, persist: bool = True):
        self._set_hunt_counter(0)
        self._set_hunt_phase_count(0)
        self._hunt_species_counts = {}
        self._hunt_recent_other_species.clear()
        self._hunt_alerted_signatures.clear()
        self._update_hunt_other_species_display()
        self._prime_hunt_baseline()
        if emit_log:
            self._log("[HUNT] Counter and phases reset", "info")
        if persist and not self._hunt_profile_applying:
            self._save_current_hunt_profile(active_override=bool(self._hunt_active))

    def _snapshot_party_for_hunt(self, party: List[Dict]) -> Dict[int, Dict[str, object]]:
        snapshot: Dict[int, Dict[str, object]] = {}
        for member in party:
            if not isinstance(member, dict):
                continue
            try:
                slot = int(member.get("slot", 0))
            except (TypeError, ValueError):
                continue
            if slot <= 0:
                continue
            name = member.get("name") if isinstance(member.get("name"), str) else ""
            is_egg = bool(member.get("is_egg", False)) or str(name).strip().lower() == "egg"
            snapshot[int(slot)] = {
                "id": int(member.get("id", 0)) if isinstance(member.get("id"), int) else 0,
                "name": str(name).strip(),
                "is_egg": bool(is_egg),
                "shiny": bool(member.get("shiny", False)),
            }
        return snapshot

    def _show_shiny_hunt_popup(self, title: str, message: str):
        self._log(f"[HUNT] {message}", "success")
        try:
            messagebox.showinfo(title, message, parent=self.root)
        except Exception:
            pass

    def _log_hunt_raw_encounter(self, encounter: Dict[str, object], game_name: str, mode: str):
        if not isinstance(encounter, dict):
            return

        try:
            species_id = int(encounter.get("species_id", 0))
        except (TypeError, ValueError):
            species_id = 0
        species_name_raw = encounter.get("species_name")
        if isinstance(species_name_raw, str) and species_name_raw.strip():
            species_name = species_name_raw.strip()
        elif self.tracker and self.tracker.pokemon_reader:
            species_name = self.tracker.pokemon_reader.get_pokemon_name(species_id)
        else:
            species_name = f"Pokemon #{species_id}"

        try:
            level_val = int(encounter.get("level", 0) or 0)
        except (TypeError, ValueError):
            level_val = 0

        try:
            enemy_count = int(encounter.get("enemy_count", 0) or 0)
        except (TypeError, ValueError):
            enemy_count = 0

        reader_meta: Dict[str, object] = {}
        if self.tracker and self.tracker.pokemon_reader:
            try:
                reader_meta = self.tracker.pokemon_reader.get_last_wild_read_meta()
            except Exception:
                reader_meta = {}
        read_reason = str(reader_meta.get("reason", "unknown"))
        enemy_count_source = str(reader_meta.get("enemy_count_source", ""))
        enemy_start = reader_meta.get("enemy_start")

        is_wild = bool(encounter.get("is_wild", True))
        is_shiny = bool(encounter.get("shiny", False))
        signature = str(encounter.get("signature", "")).strip()
        if not signature:
            signature = f"{species_id}:{level_val}:{encounter.get('personality')}:{encounter.get('ot_id')}"

        route_value = self.hunt_route_var.get().strip()
        target_id = self._get_hunt_target_pokemon_id()
        log_key = f"{game_name}|{mode}|{route_value}|{signature}|{enemy_count}|{int(is_wild)}"
        if log_key == self._hunt_last_raw_log_key:
            return

        self._hunt_last_raw_log_key = log_key
        self._hunt_last_raw_none_log_at = 0.0

        log_event(
            logging.INFO,
            "hunt_wild_read",
            game=game_name,
            mode=mode,
            route=route_value,
            target_id=target_id,
            species_id=species_id,
            species=species_name,
            level=level_val,
            shiny=is_shiny,
            enemy_count=enemy_count,
            is_wild=is_wild,
            signature=signature,
            reader_reason=read_reason,
            enemy_count_source=(enemy_count_source or None),
            enemy_start=(str(enemy_start) if enemy_start is not None else None),
        )

        mode_label = "FISHING" if mode == "Fishing Encounter Hunt" else "WILD"
        form_text = "Shiny" if is_shiny else "Normal"
        level_text = f"Lv.{level_val}" if level_val > 0 else "Lv.?"
        source_text = enemy_count_source if enemy_count_source else "unknown"
        self._log(
            f"RAW {mode_label} READ: {species_name} (#{species_id}) / {level_text} / {form_text} / wild={is_wild} / enemy_count={enemy_count} / source={source_text} / reason={read_reason}",
            "hunt",
        )

    def _log_hunt_raw_no_encounter(self, game_name: str, mode: str):
        if bool(getattr(self.retroarch, "is_waiting_for_launch", lambda: False)()):
            return
        if not bool(getattr(self.retroarch, "connected", False)):
            return

        now_ts = time.monotonic()
        if (now_ts - float(self._hunt_last_raw_none_log_at)) < 15.0:
            return

        self._hunt_last_raw_none_log_at = now_ts
        self._hunt_last_raw_log_key = None

        route_value = self.hunt_route_var.get().strip()
        target_id = self._get_hunt_target_pokemon_id()

        reader_meta: Dict[str, object] = {}
        if self.tracker and self.tracker.pokemon_reader:
            try:
                reader_meta = self.tracker.pokemon_reader.get_last_wild_read_meta()
            except Exception:
                reader_meta = {}
        read_reason = str(reader_meta.get("reason", "unknown"))
        enemy_count_source = str(reader_meta.get("enemy_count_source", ""))
        decode_attempts_raw = reader_meta.get("decode_attempts", 0)
        try:
            decode_attempts = int(decode_attempts_raw)
        except (TypeError, ValueError):
            decode_attempts = 0

        log_event(
            logging.INFO,
            "hunt_wild_read_none",
            game=game_name,
            mode=mode,
            route=route_value,
            target_id=target_id,
            reason=read_reason,
            enemy_count_source=(enemy_count_source or None),
            decode_attempts=decode_attempts,
            enemy_count=reader_meta.get("enemy_count"),
            enemy_count_addr=reader_meta.get("enemy_count_addr"),
            enemy_start=reader_meta.get("enemy_start"),
            enemy_start_candidates=reader_meta.get("enemy_start_candidates"),
            player_start_candidates=reader_meta.get("player_start_candidates"),
            player_count_candidates=reader_meta.get("player_count_candidates"),
        )

        mode_label = "FISHING" if mode == "Fishing Encounter Hunt" else "WILD"
        source_text = enemy_count_source if enemy_count_source else "unknown"
        self._log(
            f"RAW {mode_label} READ: no encounter data / Route: {route_value or '-'} / Target: #{target_id if target_id > 0 else 0} / reason={read_reason} / source={source_text} / decode_attempts={decode_attempts}",
            "hunt",
        )

    def _is_hunt_target_in_pokedex(self) -> bool:
        """Return True when the selected hunt target currently exists in tracked Pokedex state."""
        if not self.tracker:
            return False
        target_id = self._get_hunt_target_pokemon_id()
        if target_id <= 0:
            return False
        pokedex = self.tracker._last_pokedex if isinstance(self.tracker._last_pokedex, list) else []
        for pid in pokedex:
            try:
                if int(pid) == int(target_id):
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _get_soft_reset_target_state(self, encounter: Optional[Dict[str, object]], game_name: str) -> Tuple[bool, Optional[str], bool, str, int]:
        """Resolve current soft-reset target visibility from enemy encounter or party state."""
        target_id = self._get_hunt_target_pokemon_id()
        if target_id <= 0 or not self.tracker or not self.tracker.pokemon_reader:
            return False, None, False, "", 0

        if isinstance(encounter, dict):
            try:
                encounter_species_id = int(encounter.get("species_id", 0))
            except (TypeError, ValueError):
                encounter_species_id = 0
            if encounter_species_id == target_id and bool(encounter.get("is_wild", True)):
                species_name = str(encounter.get("species_name") or self.tracker.pokemon_reader.get_pokemon_name(encounter_species_id))
                encounter_signature = str(encounter.get("signature", "")).strip()
                marker = f"enemy:{encounter_signature}" if encounter_signature else f"enemy:{encounter_species_id}"
                return True, marker, bool(encounter.get("shiny", False)), species_name, encounter_species_id

        def _resolve_target_from_party(party_data: object) -> Tuple[bool, Optional[str], bool, str, int]:
            if not isinstance(party_data, list):
                return False, None, False, "", 0
            for member in party_data:
                if not isinstance(member, dict):
                    continue
                try:
                    member_species_id = int(member.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if member_species_id != target_id:
                    continue

                try:
                    slot = int(member.get("slot", 0))
                except (TypeError, ValueError):
                    slot = 0
                species_name = str(member.get("name") or self.tracker.pokemon_reader.get_pokemon_name(member_species_id))

                personality = member.get("_personality")
                ot_id = member.get("_ot_id")
                level = member.get("level")
                sig_parts = ["party", str(slot), str(member_species_id)]
                if isinstance(personality, int) and isinstance(ot_id, int):
                    sig_parts.extend([str(int(personality) & 0xFFFFFFFF), str(int(ot_id) & 0xFFFFFFFF)])
                elif isinstance(level, int):
                    sig_parts.append(str(int(level)))
                signature = ":".join(sig_parts)
                return True, signature, bool(member.get("shiny", False)), species_name, member_species_id
            return False, None, False, "", 0

        cached_party = self.tracker._last_party if isinstance(self.tracker._last_party, list) else []
        present, signature, is_shiny, species_name, species_id = _resolve_target_from_party(cached_party)
        if present:
            return present, signature, is_shiny, species_name, species_id

        # Soft-reset hunts on fresh saves can happen before collection baseline captures party;
        # do a direct live read so attempts are still counted.
        try:
            live_party = self.tracker.pokemon_reader.read_party(game_name)
        except Exception:
            live_party = []

        return _resolve_target_from_party(live_party)

    def _handle_hunt_soft_reset_progress(self, encounter: Optional[Dict[str, object]], game_name: str):
        """Track soft-reset attempts for both stationary encounters and party-based targets."""
        present, signature, is_shiny, species_name, species_id = self._get_soft_reset_target_state(encounter, game_name)
        target_in_pokedex = self._is_hunt_target_in_pokedex()
        current_target_id = self._get_hunt_target_pokemon_id()

        if current_target_id != self._hunt_soft_reset_target_id:
            self._hunt_soft_reset_target_id = current_target_id
            self._hunt_target_present = False
            self._hunt_last_target_signature = None
            self._hunt_enemy_present = False
            self._hunt_soft_reset_seen_in_pokedex = bool(target_in_pokedex)

        if not self._hunt_initialized:
            self._hunt_target_present = bool(present)
            self._hunt_last_target_signature = signature if isinstance(signature, str) and signature else None
            self._hunt_soft_reset_seen_in_pokedex = bool(target_in_pokedex)
            self._hunt_initialized = True
            return

        if not present:
            if self._hunt_target_present:
                # Transitioned from visible target to not visible; record current dex state
                # so fallback counting does not double count the same attempt.
                self._hunt_soft_reset_seen_in_pokedex = bool(target_in_pokedex)
            else:
                fallback_new_attempt = (not self._hunt_soft_reset_seen_in_pokedex) and bool(target_in_pokedex)
                if fallback_new_attempt:
                    if self._hunt_soft_reset_reset_pending:
                        self._hunt_soft_reset_reset_pending = False
                    else:
                        self._set_hunt_counter(self._hunt_counter + 1)

                    resolved_species_id = species_id if species_id > 0 else self._get_hunt_target_pokemon_id()
                    if resolved_species_id > 0:
                        resolved_species_name = species_name or self.tracker.pokemon_reader.get_pokemon_name(resolved_species_id)
                        self._log(
                            f"SOFT RESET ENCOUNTER #{self._hunt_counter}: {resolved_species_name} (#{resolved_species_id}) [{game_name}] / State: Pokedex",
                            "hunt",
                        )

                self._hunt_soft_reset_seen_in_pokedex = bool(target_in_pokedex)

            self._hunt_target_present = False
            self._hunt_last_target_signature = None
            self._hunt_enemy_present = False
            return

        normalized_signature = signature if isinstance(signature, str) and signature else None
        is_new_attempt = (not self._hunt_target_present) or (normalized_signature is not None and normalized_signature != self._hunt_last_target_signature)
        if is_new_attempt:
            if self._hunt_soft_reset_reset_pending:
                self._hunt_soft_reset_reset_pending = False
            else:
                self._set_hunt_counter(self._hunt_counter + 1)

            if species_id > 0:
                form_text = "Shiny" if is_shiny else "Normal"
                self._log(
                    f"SOFT RESET ENCOUNTER #{self._hunt_counter}: {species_name} (#{species_id}) [{game_name}] / {form_text}",
                    "hunt",
                )
            # Prevent duplicate fallback counting when Pokedex updates after a counted attempt.
            self._hunt_soft_reset_seen_in_pokedex = True

        self._hunt_target_present = True
        if normalized_signature is not None:
            self._hunt_last_target_signature = normalized_signature

        if is_shiny and species_id > 0:
            alert_key = f"Soft Reset Hunt:{normalized_signature or species_id}"
            if alert_key in self._hunt_alerted_signatures:
                return
            self._hunt_alerted_signatures.add(alert_key)
            self._show_shiny_hunt_popup(
                "Shiny Found!",
                f"Shiny found: {species_name} (#{species_id}) in {game_name}.",
            )

    def _handle_hunt_enemy_encounter(self, encounter: Dict[str, object], game_name: str):
        if not isinstance(encounter, dict):
            return

        mode = self.hunt_mode_var.get().strip()
        if mode not in {"Wild Encounter Hunt", "Fishing Encounter Hunt"}:
            return

        if not bool(encounter.get("is_wild", True)):
            self._hunt_enemy_present = False
            self._hunt_last_enemy_seen_at = 0.0
            log_event(
                logging.INFO,
                "hunt_encounter_skipped_non_wild",
                game=game_name,
                mode=mode,
                species_id=encounter.get("species_id"),
                enemy_count=encounter.get("enemy_count"),
            )
            return

        try:
            species_id = int(encounter.get("species_id", 0))
        except (TypeError, ValueError):
            species_id = 0
        if species_id <= 0:
            return

        try:
            level_val = int(encounter.get("level", 0) or 0)
        except (TypeError, ValueError):
            level_val = 0
        personality = encounter.get("personality")
        ot_id = encounter.get("ot_id")
        signature = str(encounter.get("signature", "")).strip()
        if not signature:
            signature = f"{species_id}:{level_val}:{personality}:{ot_id}"

        now_ts = time.monotonic()
        if not self._hunt_initialized:
            self._hunt_last_enemy_signature = signature
            self._hunt_enemy_present = True
            self._hunt_last_enemy_seen_at = now_ts
            self._hunt_initialized = True
            return

        same_signature = bool(signature) and signature == self._hunt_last_enemy_signature
        is_new_encounter = (not self._hunt_enemy_present) or (not same_signature)

        self._hunt_enemy_present = True
        self._hunt_last_enemy_signature = signature
        self._hunt_last_enemy_seen_at = now_ts
        if not is_new_encounter:
            return

        allowed_species = set(
            self._get_hunt_species_ids_for_selection(
                game_name,
                mode=mode,
                route_name=self.hunt_route_var.get().strip(),
            )
        )
        if allowed_species and species_id not in allowed_species:
            log_event(
                logging.INFO,
                "hunt_encounter_skipped_route_filter",
                game=game_name,
                mode=mode,
                route=self.hunt_route_var.get().strip(),
                species_id=species_id,
                allowed_count=len(allowed_species),
            )
            return

        self._record_hunt_species_encounter(species_id)
        species_counter = self._get_hunt_species_count(species_id)
        target_id = self._get_hunt_target_pokemon_id()
        target_match = target_id <= 0 or species_id == target_id
        if target_match:
            self._set_hunt_counter(self._hunt_counter + 1)
            log_event(
                logging.INFO,
                "hunt_encounter_counted",
                game=game_name,
                mode=mode,
                route=self.hunt_route_var.get().strip(),
                species_id=species_id,
                counter=self._hunt_counter,
                species_counter=species_counter,
                signature=signature,
                target_id=target_id,
            )
        else:
            log_event(
                logging.INFO,
                "hunt_encounter_non_target",
                game=game_name,
                mode=mode,
                route=self.hunt_route_var.get().strip(),
                species_id=species_id,
                species_counter=species_counter,
                counter=self._hunt_counter,
                signature=signature,
                target_id=target_id,
            )

        species_name = str(encounter.get("species_name") or self.tracker.pokemon_reader.get_pokemon_name(species_id))
        is_shiny = bool(encounter.get("shiny", False))
        form_text = "Shiny" if is_shiny else "Normal"
        encounter_label = "FISHING" if mode == "Fishing Encounter Hunt" else "WILD"
        if target_match:
            self._log(
                f"{encounter_label} TARGET ENCOUNTER #{self._hunt_counter}: {species_name} (#{species_id}) [{game_name}] / {form_text}",
                "hunt",
            )
        else:
            target_name = self.tracker.pokemon_reader.get_pokemon_name(target_id) if target_id > 0 else "Any"
            self._log(
                f"{encounter_label} ENCOUNTER (non-target): {species_name} (#{species_id}) [{game_name}] / {form_text} / Species Count: {species_counter:,} / Target: {target_name} (#{target_id})",
                "hunt",
            )

        if is_shiny and target_id > 0 and not target_match:
            self._set_hunt_phase_count(self._hunt_phase_count + 1)
            target_name = self.tracker.pokemon_reader.get_pokemon_name(target_id)
            log_event(
                logging.INFO,
                "hunt_phase_advanced",
                game=game_name,
                mode=mode,
                route=self.hunt_route_var.get().strip(),
                phase=self._hunt_phase_count,
                species_id=species_id,
                target_id=target_id,
                signature=signature,
            )
            self._log(
                f"{encounter_label} PHASE #{self._hunt_phase_count}: Shiny non-target {species_name} (#{species_id}) [{game_name}] / Target: {target_name} (#{target_id})",
                "hunt",
            )

        if is_shiny:
            alert_key = f"{mode}:{signature or species_id}:{self._hunt_counter}"
            if alert_key in self._hunt_alerted_signatures:
                return
            self._hunt_alerted_signatures.add(alert_key)
            self._show_shiny_hunt_popup(
                "Shiny Found!",
                f"Shiny found: {species_name} (#{species_id}) in {game_name}.",
            )

    def _handle_hunt_egg_progress(self, current_party: List[Dict], game_name: str):
        snapshot = self._snapshot_party_for_hunt(current_party)
        if not self._hunt_initialized:
            self._hunt_last_party_snapshot = snapshot
            self._hunt_initialized = True
            return

        target_id = self._get_hunt_target_pokemon_id()
        previous = self._hunt_last_party_snapshot
        for slot, prev_state in previous.items():
            curr_state = snapshot.get(slot)
            if not curr_state:
                continue
            if not bool(prev_state.get("is_egg", False)):
                continue
            if bool(curr_state.get("is_egg", False)):
                continue

            species_id = int(curr_state.get("id", 0)) if isinstance(curr_state.get("id"), int) else 0
            species_name = str(curr_state.get("name") or self.tracker.pokemon_reader.get_pokemon_name(species_id))
            is_shiny = bool(curr_state.get("shiny", False))

            if target_id <= 0 or species_id == target_id:
                self._set_hunt_counter(self._hunt_counter + 1)

            if is_shiny:
                alert_key = f"egg:{slot}:{species_id}:{self._hunt_counter}"
                if alert_key not in self._hunt_alerted_signatures:
                    self._hunt_alerted_signatures.add(alert_key)
                    self._show_shiny_hunt_popup(
                        "Shiny Found!",
                        f"Shiny hatch found: {species_name} (#{species_id}) in {game_name}.",
                    )

        self._hunt_last_party_snapshot = snapshot

    def _process_hunt_updates(self):
        """Poll hunt counters from live memory state."""
        if not self.is_running:
            return

        try:
            current_game = (self.tracker.game_name or "").strip()
            if current_game and current_game in self._hunt_game_options and self.hunt_game_var.get().strip() != current_game:
                self._load_last_hunt_for_game(current_game, auto_start=True)

            waiting_now = bool(self.retroarch.is_waiting_for_launch())
            if self._hunt_active:
                mode = self.hunt_mode_var.get().strip()
                # On reset/reconnect, clear encounter + target signatures so repeated
                # identical encounter signatures can still count as new attempts.
                if mode == "Soft Reset Hunt":
                    if waiting_now and not self._hunt_last_waiting_state:
                        self._hunt_last_enemy_signature = None
                        self._hunt_last_enemy_seen_at = 0.0
                        self._hunt_last_target_signature = None
                        self._hunt_enemy_present = False
                        self._hunt_target_present = False
                        self._hunt_initialized = True
                        self._hunt_soft_reset_reset_pending = False
                    elif (not waiting_now) and self._hunt_last_waiting_state:
                        self._hunt_last_enemy_signature = None
                        self._hunt_last_enemy_seen_at = 0.0
                        self._hunt_last_target_signature = None
                        self._hunt_enemy_present = False
                        self._hunt_target_present = False
                        self._hunt_initialized = True
                        self._set_hunt_counter(self._hunt_counter + 1)
                        self._hunt_soft_reset_reset_pending = True

                selected_hunt_game = self.hunt_game_var.get().strip()
                game_for_hunt = current_game if current_game in self._hunt_game_options else selected_hunt_game

                if mode == "Hatching Egg Hunt":
                    party = list(self.tracker._last_party) if isinstance(self.tracker._last_party, list) else []
                    self._handle_hunt_egg_progress(party, game_for_hunt)
                else:
                    encounter = self.tracker.pokemon_reader.read_wild_encounter(game_for_hunt) if self.tracker and self.tracker.pokemon_reader else None
                    if mode == "Soft Reset Hunt":
                        self._handle_hunt_soft_reset_progress(encounter, game_for_hunt)
                    elif mode in {"Wild Encounter Hunt", "Fishing Encounter Hunt"}:
                        if isinstance(encounter, dict):
                            self._log_hunt_raw_encounter(encounter, game_for_hunt, mode)
                            self._handle_hunt_enemy_encounter(encounter, game_for_hunt)
                        else:
                            if waiting_now or not bool(getattr(self.retroarch, "connected", False)):
                                self._hunt_last_raw_log_key = None
                            else:
                                self._log_hunt_raw_no_encounter(game_for_hunt, mode)
                            self._hunt_enemy_present = False
                            self._hunt_last_enemy_seen_at = 0.0
                    elif isinstance(encounter, dict):
                        self._handle_hunt_enemy_encounter(encounter, game_for_hunt)
                    else:
                        self._hunt_enemy_present = False
                        self._hunt_last_enemy_seen_at = 0.0

                if isinstance(self.hunt_status_label, ttk.Label):
                    self.hunt_status_label.configure(text=f"Hunt active ({mode})")
            else:
                self._hunt_enemy_present = False
                self._hunt_last_enemy_seen_at = 0.0
                if isinstance(self.hunt_status_label, ttk.Label):
                    self.hunt_status_label.configure(text="Hunt idle")

            self._hunt_last_waiting_state = waiting_now
        except Exception as exc:
            log_event(logging.WARNING, "hunt_poll_exception", error=str(exc), error_type=type(exc).__name__)

        next_delay_ms = 1000
        if self._hunt_active:
            active_mode = self.hunt_mode_var.get().strip()
            if active_mode in {"Wild Encounter Hunt", "Fishing Encounter Hunt"}:
                next_delay_ms = 250
            elif active_mode == "Soft Reset Hunt":
                next_delay_ms = 400
        self.root.after(next_delay_ms, self._process_hunt_updates)

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
        prefix = {
            "info": "INFO",
            "success": "OK",
            "error": "ERROR",
            "warning": "WARN",
            "unlock": "UNLOCK",
            "api": "API",
            "collection": "COLLECTION",
            "party": "PARTY",
            "hunt": "HUNT",
        }.get(level, "INFO")

        self.log_text.configure(state='normal')
        self.log_text.insert('end', f"[{timestamp}] {prefix}: {message}\n")
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
                self.ra_status_label.configure(text="RetroArch: Connected")
                self._detect_game(status.get("game_name"))
            else:
                self.ra_status_label.configure(text="RetroArch: Disconnected")

            if status.get("api_configured"):
                if self._api_status_state == "Not configured":
                    self._set_api_status("Configured")
            else:
                self._set_api_status("Not configured")
            self._update_sync_meta_labels()
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
                
                corrected = self.tracker.reconcile_local_unlocks()
                if corrected > 0:
                    self.tracker.save_progress(self.progress_file)
                    self._log(f"Corrected {corrected} local unlocks from save data", "info")

                # Merge with website data (fetch latest from server)
                if self.api:
                    self._merge_with_website_data(display_name)
                
                self.game_label.configure(text=f"Game: {display_name}")
                self._apply_game_theme(display_name)
                if display_name in self._hunt_game_options:
                    self._load_last_hunt_for_game(display_name, auto_start=True)
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
                server_unlocked = {str(item) for item in (unlocked_ids or [])}

                # Expand server unlock tokens using live catalog IDs/names.
                catalog = self.api._get_achievement_catalog(game_id) if self.api else []
                if isinstance(catalog, list):
                    for item in catalog:
                        if not isinstance(item, dict):
                            continue
                        catalog_id_raw = item.get("id") or item.get("achievement_id")
                        catalog_id = str(catalog_id_raw) if catalog_id_raw is not None else ""
                        catalog_string = str(item.get("string_id") or item.get("achievement_string_id") or "").strip()
                        catalog_name = str(item.get("name") or item.get("achievement_name") or "").strip().lower()
                        name_token = f"name:{catalog_name}" if catalog_name else ""

                        if catalog_id and catalog_id in server_unlocked:
                            if catalog_string:
                                server_unlocked.add(catalog_string)
                            if name_token:
                                server_unlocked.add(name_token)
                        if catalog_string and catalog_string in server_unlocked:
                            if catalog_id:
                                server_unlocked.add(catalog_id)
                            if name_token:
                                server_unlocked.add(name_token)
                        if name_token and name_token in server_unlocked:
                            if catalog_id:
                                server_unlocked.add(catalog_id)
                            if catalog_string:
                                server_unlocked.add(catalog_string)

                # Update local achievements to include server ones
                newly_added = 0
                for ach in self.tracker.achievements:
                    by_id = ach.id in server_unlocked
                    by_name = f"name:{ach.name.strip().lower()}" in server_unlocked
                    resolved = self.api._resolve_achievement_id(game_id, ach.name, ach.id) if self.api else None
                    by_resolved = resolved is not None and str(resolved) in server_unlocked
                    if (by_id or by_name or by_resolved) and not ach.unlocked:
                        ach.unlocked = True
                        ach.unlocked_at = datetime.now()
                        newly_added += 1

                if newly_added > 0:
                    self._log(f"Synced {newly_added} achievements from website", "info")
                    self.tracker.save_progress(self.progress_file)

                # Backfill locally-unlocked achievements that the server does not yet show.
                missing_on_server = []
                for ach in self.tracker.achievements:
                    if not ach.unlocked:
                        continue
                    by_id = ach.id in server_unlocked
                    by_name = f"name:{ach.name.strip().lower()}" in server_unlocked
                    resolved = self.api._resolve_achievement_id(game_id, ach.name, ach.id) if self.api else None
                    by_resolved = resolved is not None and str(resolved) in server_unlocked
                    if not (by_id or by_name or by_resolved):
                        missing_on_server.append(ach)

                for ach in missing_on_server:
                    self.tracker.post_unlock_to_platform(ach)

                if missing_on_server:
                    log_event(
                        logging.INFO,
                        "unlock_backfill_queued",
                        game=game_name,
                        count=len(missing_on_server),
                    )
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
        self._process_hunt_updates()
    
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
        self._apply_game_theme(None)
    
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
        
        self.root.after(1000, self._check_unlocks)
    
    def _threadsafe_log(self, message: str, level: str = "info"):
        """Schedule log writes from worker threads safely onto Tk main loop."""
        self.root.after(0, lambda: self._log(message, level))

    def _is_retryable_api_error(self, data: object) -> bool:
        """Return True when API errors are likely transient and worth retrying."""
        if not isinstance(data, dict):
            return True

        status = data.get("status")
        if isinstance(status, int):
            if status >= 500:
                return True
            # Retry transient client statuses only.
            if status in {408, 409, 425, 429}:
                return True
            return False

        error_text = str(data.get("error", "")).lower()
        transient_markers = (
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection refused",
            "network is unreachable",
        )
        return any(marker in error_text for marker in transient_markers)

    def _start_api_worker(self):
        """Start a single API worker to process queued sync jobs sequentially."""
        if not hasattr(self, "_api_worker_thread"):
            self._api_worker_thread = None
        if not hasattr(self, "_api_worker_stop"):
            self._api_worker_stop = threading.Event()

        if not (self.api and self.config.get("api_sync", True)):
            self._last_sync_status = "Disabled"
            self.root.after(0, self._update_sync_meta_labels)
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
                self.root.after(0, self._update_sync_meta_labels)
                success = self._process_api_item(item)
                retryable = item.get("retryable", True)
                if not success and retryable and not self._api_worker_stop.is_set():
                    retries = item.get("retries", 0)
                    if retries < 3:
                        item["retries"] = retries + 1
                        self._retry_count = item["retries"]
                        self.root.after(0, self._update_sync_meta_labels)
                        backoff_seconds = 2 ** retries
                        time.sleep(backoff_seconds)
                        self.tracker._api_queue.put(item)

                self.tracker._api_queue.task_done()
                self._last_sync_status = "Idle"
                if success:
                    self._retry_count = 0
                    self._last_api_error = ""
                self.root.after(0, self._update_sync_meta_labels)

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
            success, data = self.api.post_unlock(self.tracker.game_id, ach.id, ach.name)
            if success:
                if event_id:
                    self._sent_event_ids.add(event_id)
                    self._save_sent_events()
                if isinstance(data, dict) and data.get("skipped"):
                    self._threadsafe_log(f"Skipped platform unlock (not mapped): {ach.name}", "api")
                else:
                    self._threadsafe_log(f"Posted unlock to platform: {ach.name}", "api")
                return True
            self._last_api_error = data.get('error', 'Unknown error')
            item["retryable"] = self._is_retryable_api_error(data)
            self._threadsafe_log(f"Failed to post unlock: {self._last_api_error}", "error")
            return False

        if item_type == "collection":
            catches = item.get("catches", [])
            party = item.get("party", [])
            previous_party = item.get("previous_party", [])
            game = item.get("game", "")
            success = self._sync_collection_to_api(catches, party, game, previous_party)
            if not success:
                self._last_api_error = "Collection sync failed"
                item["retryable"] = False
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
                previous_party = update.get("previous_party", [])
                game = update["game"]
                catch_event_type = str(update.get("catch_event_type", "new_addition")).strip().lower()
                catches_int: List[int] = []
                for pokemon_id in catches:
                    try:
                        catches_int.append(int(pokemon_id))
                    except (TypeError, ValueError):
                        continue

                if catch_event_type == "new_addition":
                    soft_reset_active = bool(self._hunt_active and self.hunt_mode_var.get().strip() == "Soft Reset Hunt")
                    target_id = self._get_hunt_target_pokemon_id()
                    if soft_reset_active and target_id > 0 and catches_int and all(pid == target_id for pid in catches_int):
                        catch_event_type = "new_encounter"

                if catch_event_type == "caught":
                    catch_action = "CAUGHT"
                elif catch_event_type == "new_encounter":
                    catch_action = "NEW ENCOUNTER"
                else:
                    catch_action = "NEW ADDITION"

                # Log Pokedex entries
                for pokemon_id in catches:
                    pokemon_name = self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
                    self._log(f"[POKEDEX] {catch_action}: {pokemon_name} (#{pokemon_id})", "collection")
                    self._add_catch_to_list(pokemon_id, game, event_action=catch_action)

                # Update party display
                self._update_party_display(party, game)
                # Log party changes to tracker log (independent of API dedupe behavior).
                if party != previous_party:
                    def _normalize_member(member: Dict) -> Optional[Tuple[int, int, str]]:
                        if not isinstance(member, dict):
                            return None
                        pokemon_id = member.get("id")
                        if not isinstance(pokemon_id, int) or pokemon_id <= 0:
                            return None
                        name = member.get("name")
                        if not isinstance(name, str) or not name.strip():
                            name = self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
                        level = member.get("level")
                        try:
                            level_int = int(level) if level is not None else 0
                        except (TypeError, ValueError):
                            level_int = 0
                        return pokemon_id, level_int, name

                    previous_counter = Counter()
                    current_counter = Counter()
                    member_names: Dict[Tuple[int, int], str] = {}

                    for member in previous_party:
                        normalized = _normalize_member(member)
                        if not normalized:
                            continue
                        pokemon_id, level_int, name = normalized
                        key = (pokemon_id, level_int)
                        previous_counter[key] += 1
                        member_names.setdefault(key, name)

                    for member in party:
                        normalized = _normalize_member(member)
                        if not normalized:
                            continue
                        pokemon_id, level_int, name = normalized
                        key = (pokemon_id, level_int)
                        current_counter[key] += 1
                        member_names.setdefault(key, name)

                    initial_party_sync = not previous_party
                    delta_logged = False

                    if not initial_party_sync:
                        deposited = previous_counter - current_counter
                        added = current_counter - previous_counter

                        had_deposits = False
                        for (pokemon_id, level_int), count in deposited.items():
                            name = member_names.get((pokemon_id, level_int), self.tracker.pokemon_reader.get_pokemon_name(pokemon_id))
                            if level_int > 0:
                                line = f"Lv.{level_int} {name} deposited into PC"
                            else:
                                line = f"{name} deposited into PC"
                            for _ in range(count):
                                self._log(line, "party")
                                delta_logged = True
                                had_deposits = True

                        if had_deposits:
                            self._last_party_pc_activity_ts = time.time()

                        last_pc_activity_ts = float(getattr(self, "_last_party_pc_activity_ts", 0.0) or 0.0)
                        recent_pc_activity = bool(last_pc_activity_ts and (time.time() - last_pc_activity_ts) <= 30.0)

                        for (pokemon_id, level_int), count in added.items():
                            name = member_names.get((pokemon_id, level_int), self.tracker.pokemon_reader.get_pokemon_name(pokemon_id))
                            if level_int > 0:
                                base_line = f"Lv.{level_int} {name}"
                            else:
                                base_line = str(name)

                            for _ in range(count):
                                if recent_pc_activity or had_deposits:
                                    self._log(f"{base_line} withdrawn from PC", "party")
                                    self._last_party_pc_activity_ts = time.time()
                                else:
                                    self._log(f"{base_line} was caught!", "party")
                                    self._log(f"{base_line} was added to the party.", "party")
                                delta_logged = True

                    # Keep slot snapshot for initial party discovery and non-roster edits (e.g., reordering).
                    should_log_slots = initial_party_sync or not delta_logged
                    if should_log_slots:
                        if not party:
                            self._log("EMPTY", "party")
                        else:
                            for member in sorted(
                                (m for m in party if isinstance(m, dict)),
                                key=lambda p: int(p.get("slot", 0))
                            ):
                                line = _format_party_slot_line(
                                    member,
                                    debug_style=False,
                                    name_resolver=self.tracker.pokemon_reader.get_pokemon_name if self.tracker and self.tracker.pokemon_reader else None,
                                )
                                if line:
                                    self._log(line, "party")
                
                # Post to API
                if self.api:
                    catches_for_api = catches
                    if catch_event_type == "new_encounter":
                        catches_for_api = []

                    if catches_for_api or party != previous_party:
                        self.tracker.post_collection_to_platform(catches_for_api, party, game, previous_party=previous_party)
            except queue.Empty:
                break
        
        self.root.after(1000, self._process_collection_updates)
    
    def _sync_collection_to_api(self, catches: List[int], party: List[Dict], game: str, previous_party: Optional[List[Dict]] = None) -> bool:
        """Sync collection data to PokeAchieve API"""
        log_event(logging.INFO, "collection_sync_start", catches=len(catches), party=len(party), game=game)
        
        if not catches and not party and not previous_party:
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
                "caught_at": datetime.now().isoformat()
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
                self._last_api_error = error_msg
                self.root.after(0, self._update_sync_meta_labels)
                self._threadsafe_log(f"Failed to sync collection: {error_msg}", "error")
                print(f"[COLLECTION SYNC] Failed: {error_msg}")
                return False
        
        # Update party using Pokemon-ID deltas (fewer requests than slot-by-slot diffs).
        previous_party = previous_party or []
        previous_by_id: Dict[int, int] = {}
        for member in previous_party:
            slot = member.get("slot")
            pokemon_id = member.get("id")
            if isinstance(slot, int) and 1 <= slot <= 6 and isinstance(pokemon_id, int) and pokemon_id > 0:
                previous_by_id[pokemon_id] = slot

        current_by_id: Dict[int, int] = {}
        for member in party:
            slot = member.get("slot")
            pokemon_id = member.get("id")
            if isinstance(slot, int) and 1 <= slot <= 6 and isinstance(pokemon_id, int) and pokemon_id > 0:
                current_by_id[pokemon_id] = slot

        party_updates: List[Dict[str, object]] = []

        for pokemon_id in sorted(previous_by_id.keys()):
            if pokemon_id in current_by_id:
                continue
            party_updates.append({
                "pokemon_id": int(pokemon_id),
                "pokemon_name": self._get_pokemon_name(int(pokemon_id)),
                "caught": True,
                "shiny": False,
                "game": game,
                "in_party": False,
                "party_slot": None,
            })

        for pokemon_id in sorted(current_by_id.keys()):
            current_slot = current_by_id[pokemon_id]
            previous_slot = previous_by_id.get(pokemon_id)
            if previous_slot == current_slot:
                continue
            party_updates.append({
                "pokemon_id": int(pokemon_id),
                "pokemon_name": self._get_pokemon_name(int(pokemon_id)),
                "caught": True,
                "shiny": False,
                "game": game,
                "in_party": True,
                "party_slot": int(current_slot),
            })

        if party_updates:
            log_event(logging.INFO, "collection_sync_party_batch_send", count=len(party_updates))
            success, data = self.api.post_collection_batch(party_updates)
            if not success:
                log_event(logging.WARNING, "collection_sync_party_batch_fallback", count=len(party_updates))
                for update in party_updates:
                    success, data = self.api.post_party_update(
                        int(update["pokemon_id"]),
                        bool(update.get("in_party", False)),
                        update.get("party_slot"),
                    )
                    if not success:
                        error_msg = data.get("error", "Unknown error")
                        self._last_api_error = error_msg
                        self.root.after(0, self._update_sync_meta_labels)
                        self._threadsafe_log(f"Failed to update party: {error_msg}", "error")
                        return False
        return True

    def _get_pokemon_name(self, pokemon_id: int) -> str:
        """Get Pokemon name from ID"""
        if self.tracker and self.tracker.pokemon_reader:
            return self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
        return f"Pokemon #{pokemon_id}"

    def _add_catch_to_list(self, pokemon_id: int, game: str = "", event_action: str = "NEW ADDITION"):
        """Add Pokedex entry to recent catches list"""
        pokemon_name = self.tracker.pokemon_reader.get_pokemon_name(pokemon_id)
        self.catches_list.configure(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        game_info = f" [{game}]" if game else ""
        action = str(event_action).strip().upper()
        if action not in {"CAUGHT", "NEW ADDITION", "NEW ENCOUNTER"}:
            action = "NEW ADDITION"
        mobile_icon = "[POKEDEX]"
        self.catches_list.insert('1.0', f"[{timestamp}] {mobile_icon} {action}: {pokemon_name} (#{pokemon_id}){game_info}\n")
        self._trim_scrolled_text(self.catches_list, self._max_catch_lines)
        self.catches_list.configure(state='disabled')

    def _get_party_game_variant(self, game: str) -> str:
        if not isinstance(game, str):
            return "default"
        lowered = game.lower()

        if "firered" in lowered or "fire red" in lowered or "leafgreen" in lowered or "leaf green" in lowered:
            return "firered-leafgreen"
        if "emerald" in lowered:
            return "emerald"
        if "ruby" in lowered or "sapphire" in lowered:
            return "ruby-sapphire"
        if "crystal" in lowered:
            return "crystal"
        if "gold" in lowered:
            return "gold"
        if "silver" in lowered:
            return "silver"
        if "yellow" in lowered:
            return "yellow"
        if "red" in lowered or "blue" in lowered:
            return "red-blue"
        return "default"

    def _get_party_game_family(self, game: str) -> str:
        variant = self._get_party_game_variant(game)
        if variant in ("red-blue", "yellow"):
            return "gen1"
        if variant in ("gold", "silver", "crystal"):
            return "gen2"
        if variant in ("ruby-sapphire", "emerald"):
            return "gen3_hoenn"
        if variant == "firered-leafgreen":
            return "gen3_kanto"
        return "default"

    def _get_party_sprite_variant(self, game: str) -> Optional[str]:
        mapping = {
            "red-blue": "generation-i/red-blue",
            "yellow": "generation-i/yellow",
            "gold": "generation-ii/gold",
            "silver": "generation-ii/silver",
            "crystal": "generation-ii/crystal",
            "ruby-sapphire": "generation-iii/ruby-sapphire",
            "emerald": "generation-iii/emerald",
            "firered-leafgreen": "generation-iii/firered-leafgreen",
        }
        return mapping.get(self._get_party_game_variant(game))

    def _party_gender_badge_asset_candidates(self, family: str, gender_key: str) -> List[Path]:
        safe_family = re.sub(r"[^a-z0-9_\-]+", "_", str(family).lower()).strip("_") or "default"
        safe_gender = re.sub(r"[^a-z0-9_\-]+", "_", str(gender_key).lower()).strip("_") or "genderless"
        candidates: List[Path] = [
            self._party_gender_badge_assets_dir / f"{safe_family}_{safe_gender}.png",
            self._party_gender_badge_assets_dir / f"{safe_family}_{safe_gender}.gif",
        ]
        if safe_family != "default":
            candidates.extend([
                self._party_gender_badge_assets_dir / f"default_{safe_gender}.png",
                self._party_gender_badge_assets_dir / f"default_{safe_gender}.gif",
            ])
        return candidates

    def _party_gender_key(self, gender: str) -> str:
        if not isinstance(gender, str):
            return "genderless"
        lowered = gender.strip().lower()
        if lowered == "male":
            return "male"
        if lowered == "female":
            return "female"
        return "genderless"

    def _load_party_gender_badge_from_file(self, path: Path) -> Optional[object]:
        if not path.exists():
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except Exception as exc:
            log_event(logging.DEBUG, "party_gender_badge_load_failed", path=str(path), error=str(exc))
            return None

    def _request_party_gender_badge(self, gender: str, game: str) -> Optional[object]:
        family = self._get_party_game_family(game)
        gender_key = self._party_gender_key(gender)
        cache_key = (family, gender_key)

        cached = self._party_gender_badge_cache.get(cache_key)
        if cached is not None:
            return cached

        if cache_key in self._party_gender_badge_missing:
            return None

        for asset_path in self._party_gender_badge_asset_candidates(family, gender_key):
            if not asset_path.exists():
                continue
            loaded = self._load_party_gender_badge_from_file(asset_path)
            if loaded is not None:
                self._party_gender_badge_cache[cache_key] = loaded
                return loaded

        self._party_gender_badge_missing.add(cache_key)
        log_event(logging.DEBUG, "party_gender_badge_missing", family=family, gender=gender_key, game=game)
        return None

    def _party_shiny_badge_asset_candidates(self, family: str) -> List[Path]:
        safe_family = re.sub(r"[^a-z0-9_\-]+", "_", str(family).lower()).strip("_") or "default"
        candidates: List[Path] = [
            self._party_shiny_badge_assets_dir / f"{safe_family}_shiny.png",
            self._party_shiny_badge_assets_dir / f"{safe_family}_shiny.gif",
        ]
        if safe_family != "default":
            candidates.extend([
                self._party_shiny_badge_assets_dir / "default_shiny.png",
                self._party_shiny_badge_assets_dir / "default_shiny.gif",
            ])
        return candidates

    def _load_party_shiny_badge_from_file(self, path: Path) -> Optional[object]:
        if not path.exists():
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except Exception as exc:
            log_event(logging.DEBUG, "party_shiny_badge_load_failed", path=str(path), error=str(exc))
            return None

    def _request_party_shiny_badge(self, game: str) -> Optional[object]:
        family = self._get_party_game_family(game)
        cache_key = str(family)

        cached = self._party_shiny_badge_cache.get(cache_key)
        if cached is not None:
            return cached

        if cache_key in self._party_shiny_badge_missing:
            return None

        for asset_path in self._party_shiny_badge_asset_candidates(family):
            if not asset_path.exists():
                continue
            loaded = self._load_party_shiny_badge_from_file(asset_path)
            if loaded is not None:
                self._party_shiny_badge_cache[cache_key] = loaded
                return loaded

        self._party_shiny_badge_missing.add(cache_key)
        log_event(logging.DEBUG, "party_shiny_badge_missing", family=family, game=game)
        return None

    def _type_generation_for_game(self, game: str) -> str:
        family = self._get_party_game_family(game)
        if family == "gen1":
            return "generation-i"
        if family == "gen2":
            return "generation-ii"
        return "generation-iii"

    def _extract_types_for_generation(self, payload: Dict[str, object], generation_name: str) -> List[str]:
        gen_order = {
            "generation-i": 1,
            "generation-ii": 2,
            "generation-iii": 3,
            "generation-iv": 4,
            "generation-v": 5,
            "generation-vi": 6,
            "generation-vii": 7,
            "generation-viii": 8,
            "generation-ix": 9,
        }
        target = gen_order.get(generation_name, 3)

        def _parse_types(entries: object) -> List[str]:
            parsed: List[Tuple[int, str]] = []
            if isinstance(entries, list):
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    try:
                        slot = int(item.get("slot", 0))
                    except (TypeError, ValueError):
                        slot = 0
                    type_info = item.get("type")
                    type_name = ""
                    if isinstance(type_info, dict):
                        raw_name = type_info.get("name")
                        if isinstance(raw_name, str):
                            type_name = raw_name.strip().lower()
                    if type_name:
                        parsed.append((slot if slot > 0 else 999, type_name))
            parsed.sort(key=lambda row: row[0])
            return [name for _, name in parsed]

        current_types = _parse_types(payload.get("types"))
        resolved = list(current_types)

        history: List[Tuple[int, List[str]]] = []
        past_entries = payload.get("past_types")
        if isinstance(past_entries, list):
            for entry in past_entries:
                if not isinstance(entry, dict):
                    continue
                generation_info = entry.get("generation")
                generation_id = ""
                if isinstance(generation_info, dict):
                    raw_generation_id = generation_info.get("name")
                    if isinstance(raw_generation_id, str):
                        generation_id = raw_generation_id.strip().lower()
                generation_value = gen_order.get(generation_id)
                if generation_value is None:
                    continue
                entry_types = _parse_types(entry.get("types"))
                if entry_types:
                    history.append((generation_value, entry_types))

        history.sort(key=lambda row: row[0])
        for generation_value, entry_types in history:
            if target <= generation_value:
                resolved = list(entry_types)
                break

        if generation_name == "generation-i":
            resolved = [t for t in resolved if t not in ("dark", "steel", "fairy")]
            try:
                species_id = int(payload.get("id", 0))
            except (TypeError, ValueError):
                species_id = 0
            if species_id in (81, 82):
                resolved = ["electric"]

        if generation_name in ("generation-ii", "generation-iii"):
            resolved = [t for t in resolved if t != "fairy"]

        deduped: List[str] = []
        for t in resolved:
            if isinstance(t, str) and t and t not in deduped:
                deduped.append(t)
        return deduped[:2]

    def _species_types_download_worker(self, pokemon_id: int):
        payload: Optional[Dict[str, object]] = None
        error_text = ""
        try:
            request = urllib.request.Request(
                f"https://pokeapi.co/api/v2/pokemon/{int(pokemon_id)}",
                headers={"User-Agent": "PokeAchieveTracker/1.0"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                data = response.read()
            parsed = json.loads(data.decode("utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
        except Exception as exc:
            error_text = str(exc)

        def _complete():
            self._species_type_pending.discard(int(pokemon_id))
            if isinstance(payload, dict):
                self._species_type_cache[int(pokemon_id)] = payload
            else:
                self._species_type_failed.add(int(pokemon_id))
                if error_text:
                    log_event(logging.DEBUG, "species_type_download_failed", pokemon_id=int(pokemon_id), error=error_text)
            if self._party_display_last_party:
                self._update_party_display(self._party_display_last_party, self._party_display_last_game)
            if isinstance(self._hunt_other_sprites_frame, ttk.Frame):
                self._update_hunt_other_species_display()
            if isinstance(self._hunt_target_name_label, ttk.Label):
                self._update_hunt_target_display()

        try:
            self.root.after(0, _complete)
        except Exception:
            pass

    def _request_species_types(self, pokemon_id: int, game: str) -> Optional[List[str]]:
        try:
            pid = int(pokemon_id)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None

        payload = self._species_type_cache.get(pid)
        if isinstance(payload, dict):
            return self._extract_types_for_generation(payload, self._type_generation_for_game(game))

        if pid in self._species_type_failed or pid in self._species_type_pending:
            return None

        self._species_type_pending.add(pid)
        threading.Thread(target=self._species_types_download_worker, args=(pid,), daemon=True).start()
        return None

    def _party_type_icon_key(self, type_name: str) -> str:
        return re.sub(r"[^a-z0-9_\-]+", "_", str(type_name).lower()).strip("_")

    def _party_type_icon_asset_candidates(self, family: str, type_name: str) -> List[Path]:
        safe_family = re.sub(r"[^a-z0-9_\-]+", "_", str(family).lower()).strip("_") or "default"
        safe_type = self._party_type_icon_key(type_name) or "normal"
        candidates: List[Path] = [
            self._party_type_icon_assets_dir / f"{safe_family}_{safe_type}.png",
            self._party_type_icon_assets_dir / f"{safe_family}_{safe_type}.gif",
        ]
        if safe_family != "default":
            candidates.extend([
                self._party_type_icon_assets_dir / f"default_{safe_type}.png",
                self._party_type_icon_assets_dir / f"default_{safe_type}.gif",
            ])
        return candidates

    def _load_party_type_icon_from_file(self, path: Path) -> Optional[object]:
        if not path.exists():
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except Exception as exc:
            log_event(logging.DEBUG, "party_type_icon_load_failed", path=str(path), error=str(exc))
            return None

    def _request_party_type_icon(self, type_name: str, game: str) -> Optional[object]:
        if not isinstance(type_name, str) or not type_name.strip():
            return None
        family = self._get_party_game_family(game)
        safe_type = self._party_type_icon_key(type_name)
        cache_key = (family, safe_type)

        cached = self._party_type_icon_cache.get(cache_key)
        if cached is not None:
            return cached

        if cache_key in self._party_type_icon_missing:
            return None

        for asset_path in self._party_type_icon_asset_candidates(family, safe_type):
            if not asset_path.exists():
                continue
            loaded = self._load_party_type_icon_from_file(asset_path)
            if loaded is not None:
                self._party_type_icon_cache[cache_key] = loaded
                return loaded

        self._party_type_icon_missing.add(cache_key)
        log_event(logging.DEBUG, "party_type_icon_missing", family=family, type=safe_type, game=game)
        return None

    def _party_sprite_cache_path(self, variant: str, pokemon_id: int, shiny: bool = False) -> Path:
        safe_variant = re.sub(r"[^a-z0-9]+", "_", str(variant).lower()).strip("_") or "default"
        suffix = "_shiny" if bool(shiny) else ""
        return self._party_sprite_cache_dir / f"{safe_variant}_{int(pokemon_id)}{suffix}.png"

    def _party_sprite_urls(self, variant: Optional[str], pokemon_id: int, shiny: bool = False) -> List[str]:
        urls: List[str] = []
        pid = int(pokemon_id)
        use_shiny = bool(shiny)

        if isinstance(variant, str) and variant.strip():
            if use_shiny:
                sprite_path = f"sprites/pokemon/versions/{variant}/shiny/{pid}.png"
            else:
                sprite_path = f"sprites/pokemon/versions/{variant}/{pid}.png"
            urls.append(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/{sprite_path}")
            urls.append(f"https://cdn.jsdelivr.net/gh/PokeAPI/sprites@master/{sprite_path}")

        if use_shiny:
            urls.append(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{pid}.png")
            urls.append(f"https://cdn.jsdelivr.net/gh/PokeAPI/sprites@master/sprites/pokemon/shiny/{pid}.png")
        else:
            urls.append(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png")
            urls.append(f"https://cdn.jsdelivr.net/gh/PokeAPI/sprites@master/sprites/pokemon/{pid}.png")

        deduped: List[str] = []
        seen: Set[str] = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    def _load_party_sprite_from_file(self, path: Path) -> Optional[object]:
        if not path.exists():
            return None
        if PIL_AVAILABLE:
            try:
                with Image.open(path) as raw_img:
                    image = raw_img.convert("RGBA")
                if hasattr(Image, "Resampling"):
                    image = image.resize((self._party_sprite_size, self._party_sprite_size), Image.Resampling.NEAREST)
                else:
                    image = image.resize((self._party_sprite_size, self._party_sprite_size), Image.NEAREST)
                return ImageTk.PhotoImage(image)
            except Exception as exc:
                log_event(logging.DEBUG, "party_sprite_pil_load_failed", path=str(path), error=str(exc))
        try:
            return tk.PhotoImage(file=str(path))
        except Exception as exc:
            log_event(logging.DEBUG, "party_sprite_tk_load_failed", path=str(path), error=str(exc))
            return None

    def _party_sprite_download_worker(self, key: Tuple[str, int, bool], urls: List[str], path: Path):
        data: Optional[bytes] = None
        error_text = ""
        for url in urls:
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "PokeAchieveTracker/1.0"},
                )
                with urllib.request.urlopen(request, timeout=4) as response:
                    data = response.read()
                if data:
                    break
            except Exception as exc:
                error_text = str(exc)

        def _complete():
            self._party_sprite_pending.discard(key)
            if data:
                try:
                    path.write_bytes(data)
                    photo = self._load_party_sprite_from_file(path)
                    if photo is not None:
                        self._party_sprite_cache[key] = photo
                        if self._party_display_last_party:
                            self._update_party_display(self._party_display_last_party, self._party_display_last_game)
                        return
                except Exception as write_exc:
                    log_event(logging.DEBUG, "party_sprite_write_failed", path=str(path), error=str(write_exc))
            self._party_sprite_failed.add(key)
            if error_text:
                log_event(logging.DEBUG, "party_sprite_download_failed", urls=urls, error=error_text)
            if self._party_display_last_party:
                self._update_party_display(self._party_display_last_party, self._party_display_last_game)

        try:
            self.root.after(0, _complete)
        except Exception:
            pass

    def _request_party_sprite(self, pokemon_id: int, game: str, shiny: bool = False) -> Optional[object]:
        try:
            pid = int(pokemon_id)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None

        variant = self._get_party_sprite_variant(game)
        key_variant = variant if variant else "default"
        is_shiny = bool(shiny)
        key = (key_variant, pid, is_shiny)
        cached = self._party_sprite_cache.get(key)
        if cached is not None:
            return cached

        sprite_path = self._party_sprite_cache_path(key_variant, pid, is_shiny)
        if sprite_path.exists():
            loaded = self._load_party_sprite_from_file(sprite_path)
            if loaded is not None:
                self._party_sprite_cache[key] = loaded
                return loaded
            try:
                sprite_path.unlink()
            except OSError:
                pass

        if key in self._party_sprite_failed or key in self._party_sprite_pending:
            return None

        self._party_sprite_pending.add(key)
        urls = self._party_sprite_urls(variant, pid, is_shiny)
        threading.Thread(
            target=self._party_sprite_download_worker,
            args=(key, urls, sprite_path),
            daemon=True,
        ).start()
        return None

    def _update_party_display(self, party: List[Dict], game: str = ""):
        """Update party display in collection tab using horizontal slot cards."""
        self._party_display_last_party = [dict(member) for member in party if isinstance(member, dict)]
        self._party_display_last_game = game or ""

        by_slot: Dict[int, Dict] = {}
        for member in party:
            if not isinstance(member, dict):
                continue
            try:
                slot = int(member.get("slot", 0))
            except (TypeError, ValueError):
                continue
            if 1 <= slot <= 6:
                by_slot[slot] = member

        for slot in range(1, 7):
            widgets = self._party_slot_widgets.get(slot, {})
            title_label = widgets.get("title")
            gender_label = widgets.get("gender")
            shiny_label = widgets.get("shiny")
            sprite_label = widgets.get("sprite")
            type1_label = widgets.get("type1")
            type2_label = widgets.get("type2")
            details_label = widgets.get("details")
            moves_label = widgets.get("moves")
            member = by_slot.get(slot)

            if not member:
                if isinstance(title_label, ttk.Label):
                    title_label.configure(text="Empty")
                if isinstance(gender_label, ttk.Label):
                    gender_label.configure(text="", image="")
                    setattr(gender_label, "image", None)
                if isinstance(shiny_label, ttk.Label):
                    shiny_label.configure(text="", image="")
                    setattr(shiny_label, "image", None)
                if isinstance(sprite_label, ttk.Label):
                    sprite_label.configure(image="", text="")
                    setattr(sprite_label, "image", None)
                for type_label in (type1_label, type2_label):
                    if isinstance(type_label, ttk.Label):
                        type_label.configure(image="", text="")
                        setattr(type_label, "image", None)
                if isinstance(details_label, ttk.Label):
                    details_label.configure(text="")
                if isinstance(moves_label, ttk.Label):
                    moves_label.configure(text="")
                continue

            pokemon_id = member.get("id")
            name = member.get("name") if isinstance(member.get("name"), str) else None
            if not name and isinstance(pokemon_id, int):
                name = self._get_pokemon_name(pokemon_id)
            if not name:
                name = "Unknown"

            level_text = "--"
            try:
                level_value = int(member.get("level"))
                if level_value > 0:
                    level_text = str(level_value)
            except (TypeError, ValueError):
                pass

            gender = member.get("gender") if isinstance(member.get("gender"), str) and member.get("gender").strip() else "Unknown"
            ability = member.get("ability") if isinstance(member.get("ability"), str) and member.get("ability").strip() else "Unknown"
            nature = member.get("nature") if isinstance(member.get("nature"), str) and member.get("nature").strip() else "Unknown"
            is_shiny = bool(member.get("shiny", False))

            if isinstance(title_label, ttk.Label):
                title_label.configure(text=f"Lv.{level_text} {name}")

            if isinstance(gender_label, ttk.Label):
                badge_image = self._request_party_gender_badge(gender, game)
                if badge_image is not None:
                    gender_label.configure(image=badge_image, text="")
                    setattr(gender_label, "image", badge_image)
                else:
                    gender_label.configure(image="", text="")
                    setattr(gender_label, "image", None)

            if isinstance(shiny_label, ttk.Label):
                if is_shiny:
                    shiny_badge = self._request_party_shiny_badge(game)
                    if shiny_badge is not None:
                        shiny_label.configure(image=shiny_badge, text="")
                        setattr(shiny_label, "image", shiny_badge)
                    else:
                        shiny_label.configure(image="", text="*")
                        setattr(shiny_label, "image", None)
                else:
                    shiny_label.configure(image="", text="")
                    setattr(shiny_label, "image", None)

            if isinstance(sprite_label, ttk.Label):
                pid = int(pokemon_id) if isinstance(pokemon_id, int) else 0
                sprite_image = self._request_party_sprite(pid, game, shiny=is_shiny)
                if sprite_image is not None:
                    sprite_label.configure(image=sprite_image, text="")
                    setattr(sprite_label, "image", sprite_image)
                else:
                    status_text = "Sprite loading..."
                    variant = self._get_party_sprite_variant(game)
                    key_variant = variant if variant else "default"
                    if pid <= 0:
                        status_text = "No sprite"
                    elif (key_variant, pid, bool(is_shiny)) in self._party_sprite_failed:
                        status_text = "Sprite unavailable"
                    sprite_label.configure(image="", text=status_text)
                    setattr(sprite_label, "image", None)

            types: List[str] = []
            raw_types = member.get("types")
            if isinstance(raw_types, list):
                for value in raw_types:
                    if isinstance(value, str) and value.strip():
                        types.append(value.strip().lower())
            if not types:
                pid = int(pokemon_id) if isinstance(pokemon_id, int) else 0
                resolved_types = self._request_species_types(pid, game)
                if isinstance(resolved_types, list):
                    for value in resolved_types:
                        if isinstance(value, str) and value.strip():
                            types.append(value.strip().lower())
            types = types[:2]

            labels = [type1_label, type2_label]
            for idx, type_label in enumerate(labels):
                if not isinstance(type_label, ttk.Label):
                    continue
                if idx < len(types):
                    type_icon = self._request_party_type_icon(types[idx], game)
                    if type_icon is not None:
                        type_label.configure(image=type_icon, text="")
                        setattr(type_label, "image", type_icon)
                    else:
                        type_label.configure(image="", text="")
                        setattr(type_label, "image", None)
                else:
                    type_label.configure(image="", text="")
                    setattr(type_label, "image", None)

            if isinstance(details_label, ttk.Label):
                details_label.configure(text=f"Ability: {ability}\nNature: {nature}")

            moves: List[str] = []
            raw_moves = member.get("moves")
            if isinstance(raw_moves, list):
                for move in raw_moves:
                    if isinstance(move, str) and move.strip():
                        moves.append(move.strip())

            while len(moves) < 4:
                moves.append("-")
            moves = moves[:4]

            if isinstance(moves_label, ttk.Label):
                moves_label.configure(text="Moves:\n" + "\n".join(moves))

        game_info = f" [{game}]" if game else ""
        self.collection_label.configure(text=f"Party: {len(party)}/6 Pokemon{game_info}")

    def _on_achievement_unlock(self, achievement: Achievement):
        """Handle achievement unlock"""
        self._log(f"UNLOCKED: {achievement.name} (+{achievement.points} pts)", "unlock")
        
        self.recent_list.configure(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        rarity_emoji = {"common": "[C]", "uncommon": "[U]", "rare": "[R]", "epic": "[E]", "legendary": "[L]"}.get(achievement.rarity, "[C]")
        
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

                # Clear hunt profiles
                if self.hunt_profiles_file.exists():
                    self.hunt_profiles_file.unlink()
                self._hunt_profiles = {"version": 1, "games": {}}

                # Clear tracker state
                self.tracker.achievements = []
                self.tracker.game_name = None
                self.tracker.game_id = None
                self.tracker._last_party = []
                self.tracker._last_pokedex = []
                self.tracker._collection_baseline_initialized = False
                self.tracker._pending_party_change = None
                self.tracker._baseline_snapshot_pending = False
                self.tracker._baseline_snapshot_wait_polls = 0
                self.tracker._unlock_streaks = {}
                self.tracker._achievement_poll_count = 0
                self.tracker._warmup_logged = False
                self.tracker._startup_baseline_captured = False
                self.tracker._startup_lockout_ids = set()
                self._sent_event_ids = set()
                self._save_sent_events()
                self._set_api_status("Not configured" if not self.api else "Configured")

                self.game_label.configure(text="Game: None")
                self._apply_game_theme(None)
                self.progress_label.configure(text="0/0 (0%) - 0/0 pts")
                self.progress_bar["value"] = 0
                self.collection_label.configure(text="Caught: 0 | Shiny: 0 | Party: 0")
                self._update_party_display([], "")
                self._hunt_profile_applying = True
                self._hunt_active = False
                self._set_hunt_counter(0)
                self._set_hunt_phase_count(0)
                self._hunt_profile_applying = False
                self._hunt_species_counts = {}
                self._hunt_species_count_labels = {}
                self._hunt_recent_other_species.clear()
                self._hunt_alerted_signatures.clear()
                self._hunt_last_enemy_signature = None
                self._hunt_last_enemy_seen_at = 0.0
                self._hunt_last_target_signature = None
                self._hunt_last_raw_log_key = None
                self._hunt_last_raw_none_log_at = 0.0
                self._hunt_enemy_present = False
                self._hunt_target_present = False
                self._hunt_soft_reset_reset_pending = False
                self._hunt_soft_reset_seen_in_pokedex = False
                self._hunt_soft_reset_target_id = 0
                self._hunt_initialized = False
                self._update_hunt_other_species_display()

                self._threadsafe_log("Local app data cleared", "info")
                msgbox.showinfo("Success", "App data cleared! Restart the tracker to start fresh.")
                
            except Exception as e:
                msgbox.showerror("Error", f"Failed to clear data: {e}")
    
    def _sync_with_server(self):
        """Sync achievements with PokeAchieve.com server"""
        import tkinter.messagebox as msgbox

        if not self.api:
            msgbox.showwarning("Not Connected", 
                "No API key configured. Go to Settings -> API to add your API key.")
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
            normalized_url = PokeAchieveAPI.normalize_base_url(url_entry.get())
            self.config["api_url"] = normalized_url
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
            if normalized_url != (url_entry.get() or "").strip():
                self._log(f"Normalized API URL to {normalized_url}", "info")
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
