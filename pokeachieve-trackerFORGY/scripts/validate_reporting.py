"""Runtime validation checks for Pokedex and achievement reporting.

Usage:
  python scripts/validate_reporting.py

This is intentionally self-contained and does not require a running RetroArch instance.
"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tracker_gui import Achievement, AchievementTracker, PokeAchieveAPI


class FakeRetroArch:
    def __init__(self):
        self.memory = {}

    def _read_single(self, addr: str):
        if addr in self.memory:
            return self.memory.get(addr)
        try:
            normalized = hex(int(addr, 16))
            return self.memory.get(normalized, 0)
        except (TypeError, ValueError):
            return self.memory.get(addr, 0)

    def read_memory(self, addr: str, num_bytes: int = 1):
        if num_bytes and num_bytes > 1:
            try:
                base = int(addr, 16)
            except (TypeError, ValueError):
                return None
            return [self._read_single(hex(base + i)) for i in range(num_bytes)]
        return self._read_single(addr)

class FakeDerivedChecker:
    def check_all_badges(self) -> bool:
        return True

    def check_champion_defeated(self) -> bool:
        return True

    def check_elite_four_member(self, member_name: str) -> bool:
        return False

    def check_all_elite_four(self) -> bool:
        return False

    def check_first_steps(self) -> bool:
        return True

    def check_has_hm(self, hm_name: str) -> bool:
        return False

class StubAPI(PokeAchieveAPI):
    def __init__(self):
        super().__init__(base_url="https://example.invalid", api_key="")
        self.calls = []

    def _request(self, method: str, endpoint: str, data: dict = None):
        self.calls.append((method, endpoint, data))
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") == "emerald_pokedex_complete":
            return False, {"status": 422, "error": "numeric achievement id required"}
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") == "123":
            return True, {"ok": True}
        return False, {"status": 500, "error": "unexpected call"}

    def _resolve_achievement_id(self, game_id: int, achievement_name: str, achievement_string_id: str = None):
        if game_id == 3 and achievement_name == "Hoenn Completionist":
            return 123
        return None


class Stub404UnlockAPI(PokeAchieveAPI):
    def __init__(self):
        super().__init__(base_url="https://example.invalid", api_key="")
        self.calls = []

    def _request(self, method: str, endpoint: str, data: dict = None):
        self.calls.append((method, endpoint, data))
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") == "emerald_gym_2":
            return False, {"status": 404, "error": "Achievement not found"}
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") == "456":
            return True, {"ok": True}
        if endpoint == "/progress/update":
            return False, {"status": 405, "error": "legacy should not be called"}
        return False, {"status": 500, "error": "unexpected call"}

    def _resolve_achievement_id(self, game_id: int, achievement_name: str, achievement_string_id: str = None):
        if game_id == 3 and achievement_name == "Knuckle Badge":
            return 456
        return None


class StubCatalogUnlockAPI(PokeAchieveAPI):
    def __init__(self):
        super().__init__(base_url="https://example.invalid", api_key="")
        self.calls = []

    def _request(self, method: str, endpoint: str, data: dict = None):
        self.calls.append((method, endpoint, data))
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") == "emerald_gym_5":
            return False, {"status": 404, "error": "Achievement not found"}
        if endpoint == "/api/tracker/unlock" and data and data.get("achievement_id") in {"emerald_gym_5_server", "999"}:
            return True, {"ok": True}
        if endpoint == "/api/games/3/achievements":
            return True, [
                {"id": 999, "string_id": "emerald_gym_5_server", "name": "Balance Badge"}
            ]
        if endpoint == "/api/users/me/achievements":
            return False, {"status": 401, "error": "should not be needed when catalog lookup succeeds"}
        if endpoint == "/progress/update":
            return False, {"status": 405, "error": "legacy should not be called"}
        return False, {"status": 500, "error": "unexpected call"}


class StubProgressAPI(PokeAchieveAPI):
    def __init__(self):
        super().__init__(base_url="https://example.invalid", api_key="tracker_test_key")
        self.calls = []

    def _request(self, method: str, endpoint: str, data: dict = None):
        self.calls.append((method, endpoint, data))
        if endpoint.startswith("/api/tracker/progress/"):
            return True, {"unlocked_achievement_ids": ["1001"]}
        if endpoint == "/api/games/3/achievements":
            return True, [
                {"id": 1001, "name": "Knuckle Badge"}
            ]
        if endpoint == "/api/users/me/achievements":
            return False, {"status": 401, "error": "should not be called in API-key mode"}
        return False, {"status": 404, "error": "unexpected"}


class ReportingValidationTests(unittest.TestCase):
    def setUp(self):
        self.retro = FakeRetroArch()
        self.tracker = AchievementTracker(retroarch=self.retro, api=None)
        self.tracker.game_name = "Pokemon Emerald"
        self.tracker._derived_checker = FakeDerivedChecker()
        # Seed valid Emerald saveblock pointers for Gen 3 profile checks.
        self.retro.memory.update({
            "0x3005d8c": 0x00, "0x3005d8d": 0x50, "0x3005d8e": 0x02, "0x3005d8f": 0x02,
            "0x3005d90": 0x00, "0x3005d91": 0x60, "0x3005d92": 0x02, "0x3005d93": 0x02,
        })

    def test_gen3_badge_plausibility_is_not_contiguous_only(self):
        self.assertTrue(self.tracker._is_plausible_badge_byte(78, generation=3))
        self.assertFalse(self.tracker._is_plausible_badge_byte(78, generation=1))

    def test_gen3_gym_checks_require_contiguous_badge_progression(self):
        gym6 = Achievement(
            id="emerald_gym_6",
            name="Feather Badge",
            description="",
            category="gym",
            rarity="common",
            points=25,
            memory_address="0x02024A6C",
            memory_condition="& 0x20",
            target_value=1,
        )

        self.retro.memory["0x02024A6C"] = 0x20
        self.assertFalse(self.tracker._safe_gen3_story_check(gym6))

        self.retro.memory["0x02024A6C"] = 0x3F
        self.assertTrue(self.tracker._safe_gen3_story_check(gym6))

    def test_gen3_party_decode_rejects_bad_checksum(self):
        reader = self.tracker.pokemon_reader
        slot = [0] * 100
        slot[0] = 1
        slot[4] = 2
        # Wrong checksum at offsets 28-29 should invalidate decode.
        slot[28] = 0x34
        slot[29] = 0x12
        self.assertIsNone(reader._decode_gen3_party_species(slot, max_species_id=386))

    def test_gen3_substruct_order_table_matches_canonical(self):
        reader = self.tracker.pokemon_reader
        expected = [
            (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 2, 3, 1), (0, 3, 1, 2), (0, 3, 2, 1),
            (1, 0, 2, 3), (1, 0, 3, 2), (1, 2, 0, 3), (1, 2, 3, 0), (1, 3, 0, 2), (1, 3, 2, 0),
            (2, 0, 1, 3), (2, 0, 3, 1), (2, 1, 0, 3), (2, 1, 3, 0), (2, 3, 0, 1), (2, 3, 1, 0),
            (3, 0, 1, 2), (3, 0, 2, 1), (3, 1, 0, 2), (3, 1, 2, 0), (3, 2, 0, 1), (3, 2, 1, 0),
        ]
        self.assertEqual(reader.GEN3_PARTY_SUBSTRUCT_ORDERS, expected)

    def test_gen3_internal_species_map_to_national_dex(self):
        reader = self.tracker.pokemon_reader
        self.assertEqual(reader._normalize_gen3_species_id(251), 251)
        self.assertEqual(reader._normalize_gen3_species_id(252), 201)
        self.assertEqual(reader._normalize_gen3_species_id(276), 201)
        self.assertEqual(reader._normalize_gen3_species_id(277), 252)
        self.assertEqual(reader._normalize_gen3_species_id(310), 279)
        self.assertEqual(reader._normalize_gen3_species_id(332), 328)
        self.assertEqual(reader._normalize_gen3_species_id(410), 386)
        self.assertEqual(reader._normalize_gen3_species_id(411), 358)
        self.assertIsNone(reader._normalize_gen3_species_id(412))

    def test_gen3_party_normalizes_internal_species_output(self):
        class PartyRetroSingle:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 1
                    return 0
                if num_bytes == 100:
                    slot = [0] * 100
                    slot[84] = 22
                    return slot
                if num_bytes > 1:
                    return [0] * int(num_bytes)
                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species
        seen_max_species = []

        reader.retroarch = PartyRetroSingle()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3004",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
            "party_max_pairs": 1,
            "party_enable_offset_scan": 0,
            "party_allow_double_stride": 0,
            "party_try_double_bulk": 0,
        }

        def fake_decode(slot_data, max_species_id, allow_checksum_mismatch=False):
            seen_max_species.append(int(max_species_id))
            return 358

        reader._decode_gen3_party_species = fake_decode
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual(seen_max_species[0], 411)
            self.assertEqual(len(party), 1)
            self.assertEqual(party[0]["id"], 333)
            self.assertEqual(party[0]["level"], 22)
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode

    def test_gen3_party_prefers_contiguous_slots_when_scores_tie(self):
        class PartyRetro:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 6
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x3000 and (address - 0x3000) % 100 == 0:
                        idx = (address - 0x3000) // 100
                        if idx in {1, 3, 5}:
                            slot[0] = 100 + idx
                    if address >= 0x3004 and (address - 0x3004) % 100 == 0:
                        idx = (address - 0x3004) // 100
                        if idx in {0, 1, 2}:
                            slot[0] = 10 + idx
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetro()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3000",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode


    def test_gen3_party_sparse_slots_are_filtered_to_prefix(self):
        class PartyRetroSparse:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 0
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x3000 and (address - 0x3000) % 100 == 0:
                        idx = (address - 0x3000) // 100
                        if idx in {1, 3, 5}:
                            slot[0] = 80 + idx
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroSparse()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3000",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            slots = [member["slot"] for member in party]
            self.assertEqual(slots, [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [81, 83, 85])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode

    def test_gen3_party_forced_byte_reads_ignore_bad_bulk_data(self):
        class PartyRetroBulkBad:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 3
                    if address >= 0x3004:
                        rel = address - 0x3004
                        idx = rel // 100
                        off = rel % 100
                        if 0 <= idx < 3 and off == 0:
                            return 40 + idx
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x3004 and (address - 0x3004) % 100 == 0:
                        idx = (address - 0x3004) // 100
                        if idx == 1:
                            slot[0] = 99
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroBulkBad()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3004",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
            "party_force_byte_reads": 1,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [40, 41, 42])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode


    def test_gen3_party_retries_byte_reads_when_bulk_variants_fail(self):
        class PartyRetroBulkDecodeFail:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 3
                    if address >= 0x3004:
                        rel = address - 0x3004
                        idx = rel // 100
                        off = rel % 100
                        if 0 <= idx < 3 and off == 0:
                            return 70 + idx
                    return 0

                if num_bytes == 100:
                    return [0] * 100

                if num_bytes == 200:
                    return [0] * 200

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroBulkDecodeFail()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3004",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
            "party_force_byte_reads": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [70, 71, 72])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode


    def test_gen3_party_decodes_interleaved_double_bulk_blocks(self):
        class PartyRetroInterleaved:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 3
                    return 0

                if num_bytes == 100:
                    return [0] * 100

                if num_bytes == 200:
                    data = [0] * 200
                    if address >= 0x3004 and (address - 0x3004) % 100 == 0:
                        idx = (address - 0x3004) // 100
                        if 0 <= idx < 3:
                            data[0] = 90 + idx
                    return data

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroInterleaved()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3004",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [90, 91, 92])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode


    def test_gen3_party_recovers_interleaved_half_party_phases(self):
        class PartyRetroInterleavedPhases:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 6
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x3000 and (address - 0x3000) % 100 == 0:
                        idx = (address - 0x3000) // 100
                        if 0 <= idx < 6:
                            slot[0] = 30 + idx
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroInterleavedPhases()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3000",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
            "party_enable_offset_scan": 0,
            "party_allow_double_stride": 0,
            "party_stride_candidates": [200],
            "party_start_candidates": ["0x3000", "0x3064"],
            "party_count_candidates": ["0x3000"],
            "party_max_pairs": 4,
            "party_decode_budget_ms": 1800,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3, 4, 5, 6])
            self.assertEqual([member["id"] for member in party], [30, 31, 32, 33, 34, 35])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode


    def test_gen3_party_fallback_when_count_reads_zero(self):
        class PartyRetroZero:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 0
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x3004 and (address - 0x3004) % 100 == 0:
                        idx = (address - 0x3004) // 100
                        if idx in {0, 1, 2}:
                            slot[0] = 20 + idx
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroZero()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3000",
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [20, 21, 22])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode

    def test_gen3_party_uses_configured_candidate_addresses(self):
        class PartyRetroCandidates:
            def read_memory(self, addr: str, num_bytes: int = 1):
                address = int(addr, 16)
                if num_bytes == 1:
                    if address == 0x3000:
                        return 0
                    if address == 0x4000:
                        return 3
                    return 0

                if num_bytes == 100:
                    slot = [0] * 100
                    if address >= 0x4004 and (address - 0x4004) % 100 == 0:
                        idx = (address - 0x4004) // 100
                        if idx in {0, 1, 2}:
                            slot[0] = 50 + idx
                    return slot

                return 0

        reader = self.tracker.pokemon_reader
        original_retro = reader.retroarch
        original_config_getter = reader.get_game_config
        original_decode = reader._decode_gen3_party_species

        reader.retroarch = PartyRetroCandidates()
        reader.get_game_config = lambda game_name: {
            "gen": 3,
            "layout_id": "gen3_emerald",
            "party_count": "0x3000",
            "party_start": "0x3004",
            "party_count_candidates": ["0x3000", "0x4000"],
            "party_start_candidates": ["0x3004", "0x4004"],
            "party_slot_size": 100,
            "party_use_pointer_layout": 0,
        }
        reader._decode_gen3_party_species = lambda slot_data, max_species_id: int(slot_data[0]) if int(slot_data[0]) > 0 else None
        try:
            party = reader.read_party("Pokemon Emerald")
            self.assertEqual([member["slot"] for member in party], [1, 2, 3])
            self.assertEqual([member["id"] for member in party], [50, 51, 52])
        finally:
            reader.retroarch = original_retro
            reader.get_game_config = original_config_getter
            reader._decode_gen3_party_species = original_decode

    def test_gen3_gym_derived_from_progression_flags(self):
        # Pointer resolves to 0x02025000 from setUp; flags array starts at +0x1270.
        flags_base = 0x02025000 + 0x1270
        self.retro.memory[hex(flags_base + 0x14)] = 0xE0  # flags 0xA5..0xA7
        self.retro.memory[hex(flags_base + 0x15)] = 0x03  # flags 0xA8..0xA9
        self.retro.memory["0x02024A6C"] = 0x00

        gym5 = Achievement(
            id="emerald_gym_5",
            name="Balance Badge",
            description="",
            category="gym",
            rarity="common",
            points=25,
            memory_address="0x02024A6C",
            memory_condition="& 0x10",
            target_value=1,
        )
        gym6 = Achievement(
            id="emerald_gym_6",
            name="Feather Badge",
            description="",
            category="gym",
            rarity="common",
            points=25,
            memory_address="0x02024A6C",
            memory_condition="& 0x20",
            target_value=1,
        )

        self.assertTrue(self.tracker._check_derived_with_config(gym5))
        self.assertFalse(self.tracker._check_derived_with_config(gym6))

    def test_reconcile_local_unlocks_drops_impossible_gen3_gym_unlocks(self):
        flags_base = 0x02025000 + 0x1270
        self.retro.memory[hex(flags_base + 0x14)] = 0xE0
        self.retro.memory[hex(flags_base + 0x15)] = 0x03

        gym5 = Achievement(
            id="emerald_gym_5",
            name="Balance Badge",
            description="",
            category="gym",
            rarity="common",
            points=25,
            memory_address="0x02024A6C",
            memory_condition="& 0x10",
            target_value=1,
            unlocked=True,
        )
        gym6 = Achievement(
            id="emerald_gym_6",
            name="Feather Badge",
            description="",
            category="gym",
            rarity="common",
            points=25,
            memory_address="0x02024A6C",
            memory_condition="& 0x20",
            target_value=1,
            unlocked=True,
        )
        self.tracker.achievements = [gym5, gym6]

        corrected = self.tracker.reconcile_local_unlocks()
        self.assertEqual(corrected, 1)
        self.assertTrue(gym5.unlocked)
        self.assertFalse(gym6.unlocked)

    def test_validation_profile_keeps_fallback_defaults(self):
        self.tracker.validation_profiles = {
            "default_by_gen": {
                "3": {
                    "max_major_unlocks_per_poll": 1,
                }
            }
        }
        profile = self.tracker._get_validation_profile()
        self.assertEqual(profile["max_major_unlocks_per_poll"], 1)
        self.assertIn("unlock_confirmations_default", profile)
        self.assertIn("collection_baseline_confirmations", profile)
        self.assertIn("startup_lockout_enabled", profile)
        self.assertIn("startup_max_unlocks_per_poll", profile)
        self.assertIn("startup_max_major_unlocks_per_poll", profile)
        self.assertIn("startup_unlock_confirmations_default", profile)
        self.assertIn("startup_unlock_confirmations_gym_gen3", profile)

    def test_validate_profile_does_not_require_missing_gen3_champion_address(self):
        validation = self.tracker.pokemon_reader.validate_memory_profile("Pokemon Emerald")
        self.assertNotIn("champion_address:missing", validation.get("failures", []))
        self.assertTrue(validation.get("ok"))

    def test_validate_profile_treats_gen3_pointer_reads_as_warning(self):
        for addr in ["0x3005d8c", "0x3005d8d", "0x3005d8e", "0x3005d8f", "0x3005d90", "0x3005d91", "0x3005d92", "0x3005d93"]:
            self.retro.memory.pop(addr, None)
        validation = self.tracker.pokemon_reader.validate_memory_profile("Pokemon Emerald")
        self.assertTrue(validation.get("ok"))
        self.assertIn("saveblock1_ptr:unreadable", validation.get("warnings", []))

    def test_progress_fetch_augments_with_name_tokens(self):
        api = StubProgressAPI()
        ok, unlocked = api.get_progress(3)
        self.assertTrue(ok)
        self.assertIn("1001", unlocked)
        self.assertIn("name:knuckle badge", unlocked)
        self.assertFalse(any(call[1] == "/api/users/me/achievements" for call in api.calls))

    def test_pokedex_count_hint_mismatch_falls_back_to_last_known(self):
        self.tracker.achievements = [
            Achievement(
                id="emerald_pokedex_10",
                name="Junior Researcher",
                description="",
                category="pokedex",
                rarity="common",
                points=20,
                memory_address="0x03005F28",
                memory_condition=">= 10",
                target_value=10,
            )
        ]
        self.retro.memory["0x03005F28"] = 15
        self.tracker._last_pokedex = list(range(1, 16))
        self.tracker.pokemon_reader.read_pokedex = lambda game, count_hint=None: list(range(1, 56))
        self.tracker._read_pokedex_count_hint = lambda: 15

        current = self.tracker._read_current_pokedex_caught()
        self.assertEqual(len(current), 15)

    def test_gen3_does_not_infer_count_hint_from_achievement_memory(self):
        self.tracker.achievements = [
            Achievement(
                id="emerald_pokedex_10",
                name="Junior Researcher",
                description="",
                category="pokedex",
                rarity="common",
                points=20,
                memory_address="0x03005F28",
                memory_condition=">= 10",
                target_value=10,
            )
        ]
        self.retro.memory["0x03005F28"] = 55
        self.assertIsNone(self.tracker._read_pokedex_count_hint())

    def test_gen3_read_pokedex_prefers_caught_even_when_hint_matches_seen(self):
        reader = self.tracker.pokemon_reader
        reader.get_game_config = lambda game: {
            "gen": 3,
            "max_pokemon": 386,
            "pokedex_caught": "0xCATCH",
            "pokedex_seen": "0xSEEN",
        }
        reader._read_pokedex_flags = lambda addr, max_pokemon: (list(range(1, 16)) if addr == "0xCATCH" else list(range(1, 56)))

        current = reader.read_pokedex("Pokemon Emerald", count_hint=55)
        self.assertEqual(len(current), 15)

    def test_pokedex_complete_uses_target_value(self):
        ach = Achievement(
            id="emerald_pokedex_complete",
            name="Hoenn Completionist",
            description="",
            category="pokedex",
            rarity="epic",
            points=500,
            memory_address="",
            memory_condition="",
            target_value=202,
        )
        self.tracker._read_current_pokedex_caught = lambda: list(range(1, 206))
        self.assertTrue(self.tracker._check_derived_with_config(ach))

        self.tracker._read_current_pokedex_caught = lambda: list(range(1, 202))
        self.assertFalse(self.tracker._check_derived_with_config(ach))

    def test_legendary_group_checks_require_full_group(self):
        ach = Achievement(
            id="emerald_legendary_latias_latios",
            name="Eon Duo Hunter",
            description="",
            category="legendary",
            rarity="epic",
            points=350,
            memory_address="",
            memory_condition="",
        )
        self.tracker._read_current_pokedex_caught = lambda: [380]
        self.assertFalse(self.tracker._check_derived_with_config(ach))

        self.tracker._read_current_pokedex_caught = lambda: [380, 381]
        self.assertTrue(self.tracker._check_derived_with_config(ach))

    def test_pokedex_category_prefers_derived_even_with_memory_fields(self):
        self.tracker.validation_profiles = {
            "default_by_gen": {
                "3": {
                    "unlock_warmup_polls": 0,
                    "unlock_confirmations_default": 1,
                    "unlock_confirmations_legendary": 1,
                    "unlock_confirmations_gym_gen3": 1,
                    "max_unlocks_per_poll": 10,
                    "max_major_unlocks_per_poll": 10,
                    "max_legendary_unlocks_per_poll": 10,
                    "max_new_catches_per_poll": 10,
                    "collection_baseline_confirmations": 1,
                    "startup_lockout_enabled": 0,
                }
            }
        }
        pokedex_ach = Achievement(
            id="emerald_pokedex_10",
            name="Junior Researcher",
            description="",
            category="pokedex",
            rarity="common",
            points=20,
            memory_address="0xDEADBEEF",
            memory_condition=">= 10",
            target_value=10,
        )
        self.tracker.achievements = [pokedex_ach]
        self.tracker._read_current_pokedex_caught = lambda: list(range(1, 21))

        unlocked = self.tracker.check_achievements()
        self.assertEqual(len(unlocked), 1)
        self.assertTrue(pokedex_ach.unlocked)

    def test_startup_window_unlocks_existing_starter_and_badges(self):
        self.tracker.validation_profiles = {
            "default_by_gen": {
                "3": {
                    "unlock_warmup_polls": 0,
                    "unlock_confirmations_default": 2,
                    "unlock_confirmations_legendary": 3,
                    "unlock_confirmations_gym_gen3": 2,
                    "startup_unlock_confirmations_default": 1,
                    "startup_unlock_confirmations_legendary": 2,
                    "startup_unlock_confirmations_gym_gen3": 1,
                    "max_unlocks_per_poll": 3,
                    "max_major_unlocks_per_poll": 2,
                    "startup_max_unlocks_per_poll": 12,
                    "startup_max_major_unlocks_per_poll": 10,
                    "max_legendary_unlocks_per_poll": 1,
                    "max_new_catches_per_poll": 20,
                    "collection_baseline_confirmations": 1,
                    "startup_lockout_enabled": 0,
                    "startup_snapshot_window_polls": 30,
                }
            }
        }
        self.retro.memory["0x02024A6C"] = 0x1F
        flags_base = 0x02025000 + 0x1270
        self.retro.memory[hex(flags_base + 0x14)] = 0xE0
        self.retro.memory[hex(flags_base + 0x15)] = 0x03
        self.tracker.pokemon_reader.read_party = lambda game: [{"id": 255, "level": 5, "slot": 1}]
        self.tracker._read_current_pokedex_caught = lambda: [255]

        starter = Achievement(
            id="emerald_starter_chosen",
            name="First Steps",
            description="",
            category="story",
            rarity="common",
            points=10,
            memory_address="0x02024A68",
            memory_condition="!= 0",
            target_value=1,
        )

        gym_conditions = ["& 0x01", "& 0x02", "& 0x04", "& 0x08", "& 0x10"]
        gyms = []
        for idx, condition in enumerate(gym_conditions, start=1):
            gyms.append(
                Achievement(
                    id=f"emerald_gym_{idx}",
                    name=f"Gym {idx}",
                    description="",
                    category="gym",
                    rarity="common",
                    points=25,
                    memory_address="0x02024A6C",
                    memory_condition=condition,
                    target_value=1,
                )
            )

        self.tracker.achievements = [starter, *gyms]

        unlocked = self.tracker.check_achievements()
        unlocked_ids = {ach.id for ach in unlocked}
        self.assertIn("emerald_starter_chosen", unlocked_ids)
        for idx in range(1, 6):
            self.assertIn(f"emerald_gym_{idx}", unlocked_ids)

    def test_party_change_queues_collection_update(self):
        self.tracker._collection_baseline_initialized = True
        self.tracker._last_pokedex = [1, 4]
        self.tracker._last_party = [
            {"id": 25, "level": 15, "slot": 1},
            {"id": 10, "level": 7, "slot": 2},
        ]

        self.tracker._read_current_pokedex_caught = lambda: [1, 4]
        self.tracker.pokemon_reader.read_party = lambda game: [
            {"id": 10, "level": 7, "slot": 1},
            {"id": 25, "level": 15, "slot": 2},
        ]

        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_queue.empty())
        update = self.tracker._collection_queue.get_nowait()
        self.assertEqual(update["catches"], [])
        self.assertEqual(update["previous_party"], [{"id": 25, "level": 15, "slot": 1}, {"id": 10, "level": 7, "slot": 2}])
        self.assertEqual(update["game"], "Pokemon Emerald")

    def test_party_drop_with_incomplete_decode_requires_retry_confirmation(self):
        self.tracker._collection_baseline_initialized = True
        self.tracker._last_pokedex = [1, 4, 7]
        self.tracker._last_party = [
            {"id": 25, "level": 15, "slot": 1},
            {"id": 10, "level": 7, "slot": 2},
            {"id": 12, "level": 9, "slot": 3},
        ]
        self.tracker._pending_party_change = None

        self.tracker._read_current_pokedex_caught = lambda: [1, 4, 7]
        self.tracker.pokemon_reader.read_party = lambda game: [
            {"id": 25, "level": 15, "slot": 1},
            {"id": 12, "level": 9, "slot": 2},
        ]
        self.tracker.pokemon_reader.get_last_party_read_meta = lambda: {
            "expected_count": 3,
            "decoded_count": 2,
            "incomplete": True,
        }

        self.tracker.check_collection()
        self.assertTrue(self.tracker._collection_queue.empty())
        self.assertEqual(len(self.tracker._last_party), 3)
        self.assertIsNotNone(self.tracker._pending_party_change)

        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_queue.empty())
        update = self.tracker._collection_queue.get_nowait()
        self.assertEqual(len(update["previous_party"]), 3)
        self.assertEqual(len(update["party"]), 2)
        self.assertEqual(len(self.tracker._last_party), 2)
        self.assertIsNone(self.tracker._pending_party_change)

    def test_party_drop_with_complete_decode_updates_immediately(self):
        self.tracker._collection_baseline_initialized = True
        self.tracker._last_pokedex = [1, 4, 7]
        self.tracker._last_party = [
            {"id": 25, "level": 15, "slot": 1},
            {"id": 10, "level": 7, "slot": 2},
            {"id": 12, "level": 9, "slot": 3},
        ]
        self.tracker._pending_party_change = None

        self.tracker._read_current_pokedex_caught = lambda: [1, 4, 7]
        self.tracker.pokemon_reader.read_party = lambda game: [
            {"id": 25, "level": 15, "slot": 1},
            {"id": 12, "level": 9, "slot": 2},
        ]
        self.tracker.pokemon_reader.get_last_party_read_meta = lambda: {
            "expected_count": 2,
            "decoded_count": 2,
            "incomplete": False,
        }

        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_queue.empty())
        update = self.tracker._collection_queue.get_nowait()
        self.assertEqual(len(update["previous_party"]), 3)
        self.assertEqual(len(update["party"]), 2)
        self.assertEqual(len(self.tracker._last_party), 2)
        self.assertIsNone(self.tracker._pending_party_change)

    def test_collection_baseline_defers_empty_party_sync_until_party_ready(self):
        self.tracker._collection_baseline_initialized = False
        self.tracker._read_current_pokedex_caught = lambda: [1, 2, 3]
        self.tracker.pokemon_reader.read_party = lambda game: []

        # First call seeds baseline candidate.
        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_baseline_initialized)

        # Second call establishes baseline but defers startup sync because party is empty.
        self.tracker.check_collection()
        self.assertTrue(self.tracker._collection_baseline_initialized)
        self.assertTrue(self.tracker._baseline_snapshot_pending)
        self.assertTrue(self.tracker._collection_queue.empty())

        # Party appears; deferred baseline snapshot should flush with catches + party once.
        self.tracker.pokemon_reader.read_party = lambda game: [{"id": 25, "level": 5, "slot": 1}]
        self.tracker.check_collection()
        self.assertFalse(self.tracker._baseline_snapshot_pending)
        self.assertFalse(self.tracker._collection_queue.empty())
        update = self.tracker._collection_queue.get_nowait()
        self.assertEqual(update["catches"], [1, 2, 3])
        self.assertEqual(update["party"], [{"id": 25, "level": 5, "slot": 1}])

    def test_collection_baseline_requires_stable_read(self):
        self.tracker._collection_baseline_initialized = False
        self.tracker.pokemon_reader.read_party = lambda game: []
        self.tracker._read_current_pokedex_caught = lambda: [1, 2, 3]

        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_baseline_initialized)

        self.tracker.check_collection()
        self.assertTrue(self.tracker._collection_baseline_initialized)

    def test_collection_startup_snapshot_from_large_spike(self):
        self.tracker._collection_baseline_initialized = True
        self.tracker._last_pokedex = list(range(1, 11))
        self.tracker._last_party = []
        self.tracker._achievement_poll_count = 8
        catches = list(range(1, 65))
        self.tracker._read_current_pokedex_caught = lambda: catches
        self.tracker.pokemon_reader.read_party = lambda game: []

        self.tracker.check_collection()
        self.assertFalse(self.tracker._collection_queue.empty())
        update = self.tracker._collection_queue.get_nowait()
        self.assertEqual(len(update["catches"]), 64)

    def test_unlock_reporting_retries_with_numeric_id(self):
        api = StubAPI()
        ok, data = api.post_unlock(3, "emerald_pokedex_complete", "Hoenn Completionist")
        self.assertTrue(ok)
        self.assertEqual(data.get("ok"), True)

        unlock_calls = [call for call in api.calls if call[1] == "/api/tracker/unlock"]
        self.assertTrue(unlock_calls)
        self.assertTrue(any(call[2].get("achievement_id") == "123" for call in unlock_calls))

    def test_unlock_404_achievement_not_found_retries_id_and_skips_legacy(self):
        api = Stub404UnlockAPI()
        ok, data = api.post_unlock(3, "emerald_gym_2", "Knuckle Badge")
        self.assertTrue(ok)
        self.assertEqual(data.get("ok"), True)
        self.assertFalse(any(call[1] == "/progress/update" for call in api.calls))

    def test_unlock_404_uses_game_catalog_for_numeric_id(self):
        api = StubCatalogUnlockAPI()
        ok, data = api.post_unlock(3, "emerald_gym_5", "Balance Badge")
        self.assertTrue(ok)
        self.assertEqual(data.get("ok"), True)
        self.assertTrue(any(call[1] == "/api/games/3/achievements" for call in api.calls))
        self.assertFalse(any(call[1] == "/progress/update" for call in api.calls))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReportingValidationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
