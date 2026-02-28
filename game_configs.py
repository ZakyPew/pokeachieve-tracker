"""
Game Memory Configuration for PokeAchieve Tracker
Centralized memory addresses and derived achievement logic per generation
"""

from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class GameMemoryConfig:
    """Memory configuration for a Pokemon game"""
    name: str
    platform: str  # gb, gbc, gba
    generation: int  # 1, 2, 3

    # Pokedex
    pokedex_caught_start: str  # Start of caught flags
    badge_address: str  # Address containing all badge flags
    party_count_address: str
    party_start_address: str
    party_slot_size: int

    # Optional fields with defaults
    pokedex_seen_start: Optional[str] = None  # Start of seen flags (if different)
    max_pokemon: int = 151
    badge_count: int = 8
    elite_four_addresses: Optional[List[str]] = None
    champion_address: Optional[str] = None
    hall_of_fame_address: Optional[str] = None  # Gen 3 uses this instead
    have_starter_address: Optional[str] = None
    legendary_addresses: Optional[Dict[str, str]] = None


# === GENERATION 1 (Red, Blue, FireRed, LeafGreen) ===
GEN1_CONFIG = GameMemoryConfig(
    name="Generation 1 (RGBY/FRLG)",
    platform="gb",
    generation=1,
    pokedex_caught_start="0xD30A",  # Caught flags (not seen!)
    pokedex_seen_start="0xD2F7",  # Seen flags
    max_pokemon=151,
    badge_address="0xD356",
    badge_count=8,
    party_count_address="0xD16B",
    party_start_address="0xD16B",
    party_slot_size=44,
    elite_four_addresses=["0xD6E0", "0xD6E1", "0xD6E2", "0xD6E3"],
    champion_address="0xD357",
    have_starter_address="0xD16B",  # First party slot species
)

# === GENERATION 2 (Gold, Silver, Crystal) ===
GEN2_CONFIG = GameMemoryConfig(
    name="Generation 2 (GSC)",
    platform="gbc",
    generation=2,
    pokedex_caught_start="0xDE3C",  # Caught flags
    pokedex_seen_start="0xD929",  # Seen flags
    max_pokemon=251,
    badge_address="0xD35C",  # Different from Gen 1!
    badge_count=8,
    party_count_address="0xDA22",
    party_start_address="0xDA22",
    party_slot_size=48,
    elite_four_addresses=["0xD6E4", "0xD6E5", "0xD6E6", "0xD6E7"],  # Approximate
    champion_address="0xD6E8",
    have_starter_address="0xDA22",
)

# === GENERATION 3 - RSE (Ruby, Sapphire, Emerald) ===
# Hoenn region games - different memory layout than FRLG
RSE_CONFIG = GameMemoryConfig(
    name="Generation 3 - RSE (Ruby/Sapphire/Emerald)",
    platform="gba",
    generation=3,
    pokedex_caught_start="0x02024D0C",  # RSE - using verified working address
    pokedex_seen_start="0x02024C0C",    # RSE - seen flags
    max_pokemon=386,  # Full national dex
    badge_address="0x02024A6C",         # RSE badge flags
    badge_count=8,
    party_count_address="0x02024284",   # RSE party count
    party_start_address="0x02024284",   # RSE party start
    party_slot_size=100,
    hall_of_fame_address="0x02024A70",  # RSE Hall of Fame
    have_starter_address="0x02024284",  # RSE starter check
)

# === GENERATION 3 - FRLG (FireRed, LeafGreen) ===
# Kanto remakes - different memory layout than RSE
FRLG_CONFIG = GameMemoryConfig(
    name="Generation 3 - FRLG (FireRed/LeafGreen)",
    platform="gba",
    generation=3,
    pokedex_caught_start="0x02024D0C",  # FRLG - using verified working address
    pokedex_seen_start="0x02024C0C",    # FRLG - seen flags
    max_pokemon=386,  # Full national dex
    badge_address="0x02024A6C",         # FRLG badge flags (same as RSE)
    badge_count=8,
    party_count_address="0x02024284",   # FRLG party count (same as RSE)
    party_start_address="0x02024284",   # FRLG party start (same as RSE)
    party_slot_size=100,
    hall_of_fame_address="0x02024A70",  # FRLG Hall of Fame (same as RSE)
    have_starter_address="0x02024284",  # FRLG starter check (same as RSE)
)

# === GAME CONFIGURATION MAPPING ===
GAME_CONFIGS: Dict[str, GameMemoryConfig] = {
    # Gen 1
    "Pokemon Red": GEN1_CONFIG,
    "Pokemon Blue": GEN1_CONFIG,

    # Gen 2
    "Pokemon Gold": GEN2_CONFIG,
    "Pokemon Silver": GEN2_CONFIG,
    "Pokemon Crystal": GEN2_CONFIG,

    # Gen 3 - RSE (Ruby, Sapphire, Emerald)
    "Pokemon Ruby": RSE_CONFIG,
    "Pokemon Sapphire": RSE_CONFIG,
    "Pokemon Emerald": RSE_CONFIG,
    
    # Gen 3 - FRLG (FireRed, LeafGreen) - separate config with different addresses
    "Pokemon FireRed": FRLG_CONFIG,
    "Pokemon LeafGreen": FRLG_CONFIG,
}


def get_game_config(game_name: str) -> Optional[GameMemoryConfig]:
    """Get memory configuration for a game"""
    return GAME_CONFIGS.get(game_name)


def get_generation(game_name: str) -> int:
    """Get generation number for a game"""
    config = get_game_config(game_name)
    return config.generation if config else 1


def get_platform(game_name: str) -> str:
    """Get platform (gb/gbc/gba) for a game"""
    config = get_game_config(game_name)
    return config.platform if config else "gb"


# === DERIVED ACHIEVEMENT CHECKERS ===
# These replace the hardcoded methods in tracker_gui.py

class DerivedAchievementChecker:
    """Checks achievements that require calculation from multiple memory locations"""

    def __init__(self, retroarch_client, game_name: str):
        self.retroarch = retroarch_client
        self.game_name = game_name
        self.config = get_game_config(game_name)
        if not self.config:
            raise ValueError(f"No configuration for game: {game_name}")

    def read_memory(self, addr: str) -> Optional[int]:
        """Read a single byte from memory"""
        return self.retroarch.read_memory(addr)

    def read_pokedex_caught(self) -> List[int]:
        """Read all caught Pokemon IDs from Pokedex"""
        if not self.config:
            return []

        caught = []
        addr = int(self.config.pokedex_caught_start, 16)
        num_bytes = (self.config.max_pokemon + 7) // 8

        for byte_idx in range(num_bytes):
            byte_val = self.read_memory(hex(addr + byte_idx))
            if byte_val is None:
                continue

            for bit_idx in range(8):
                pokemon_id = byte_idx * 8 + bit_idx + 1
                if pokemon_id > self.config.max_pokemon:
                    break
                if (byte_val >> bit_idx) & 1:
                    caught.append(pokemon_id)

        return caught

    def get_caught_count(self) -> int:
        """Get total number of caught Pokemon"""
        return len(self.read_pokedex_caught())

    def check_all_badges(self) -> bool:
        """Check if all gym badges are obtained"""
        if not self.config:
            return False

        badge_byte = self.read_memory(self.config.badge_address)
        if badge_byte is None:
            return False

        # All badges = all N bits set
        expected = (1 << self.config.badge_count) - 1
        return badge_byte == expected

    def check_champion_defeated(self) -> bool:
        """Check if champion/E4 has been defeated"""
        if not self.config:
            return False

        if self.config.champion_address:
            value = self.read_memory(self.config.champion_address)
            return value is not None and value > 0

        if self.config.hall_of_fame_address:
            value = self.read_memory(self.config.hall_of_fame_address)
            return value is not None and value > 0

        return False

    def check_elite_four_member(self, member_name: str) -> bool:
        """Check if specific Elite Four member is defeated"""
        if not self.config or not self.config.elite_four_addresses:
            return False

        # Map names to indices
        e4_names = ["lorelei", "bruno", "agatha", "lance"]
        if member_name.lower() not in e4_names:
            return False

        idx = e4_names.index(member_name.lower())
        if idx >= len(self.config.elite_four_addresses):
            return False

        value = self.read_memory(self.config.elite_four_addresses[idx])
        return value is not None and value > 0

    def check_all_elite_four(self) -> bool:
        """Check if all Elite Four members are defeated"""
        if not self.config or not self.config.elite_four_addresses:
            # For Gen 3, check Hall of Fame instead
            return self.check_champion_defeated()

        for addr in self.config.elite_four_addresses:
            value = self.read_memory(addr)
            if value is None or value == 0:
                return False

        return True

    def check_legendary_caught(self, legendary_name: str) -> bool:
        """Check if specific legendary is caught via Pokedex"""
        caught = self.read_pokedex_caught()

        # Legendary Pokemon IDs by name
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

        pokemon_id = legendary_ids.get(legendary_name.lower())
        if pokemon_id:
            return pokemon_id in caught

        return False

    def check_all_legendary_birds(self) -> bool:
        """Check if all 3 legendary birds are caught"""
        caught = self.read_pokedex_caught()
        birds = [144, 145, 146]  # Articuno, Zapdos, Moltres
        return all(bird in caught for bird in birds)

    def check_all_legendaries(self) -> bool:
        """Check if all legendaries for this generation are caught"""
        caught = self.read_pokedex_caught()

        if self.config.generation == 1:
            legendaries = [144, 145, 146, 150]  # Birds + Mewtwo
        elif self.config.generation == 2:
            legendaries = [243, 244, 245, 249, 250]  # Beasts + Tower duo
        elif self.config.generation == 3:
            legendaries = [377, 378, 379, 380, 381, 382, 383, 384]  # Regis + Eon + Weather
        else:
            return False

        return all(leg in caught for leg in legendaries)

    def check_first_steps(self) -> bool:
        """Check if player has started (has a starter Pokemon in party)"""
        if not self.config:
            return False

        # Read party count
        count = self.read_memory(self.config.party_count_address)
        if count is None or count == 0 or count > 6:
            return False

        # Check first party slot for starter
        starter = self.read_memory(self.config.party_start_address)

        # Starters by generation
        gen1_starters = {1, 4, 7}  # Bulbasaur, Charmander, Squirtle
        gen2_starters = {152, 155, 158}  # Chikorita, Cyndaquil, Totodile
        gen3_starters = {252, 255, 258}  # Treecko, Torchic, Mudkip

        if self.config.generation == 1:
            return starter in gen1_starters
        elif self.config.generation == 2:
            return starter in gen2_starters
        elif self.config.generation == 3:
            return starter in gen3_starters

        return False

    def check_pokemon_master(self) -> bool:
        """Check Pokemon Master: All badges, Champion, and Complete Pokedex"""
        # All badges
        if not self.check_all_badges():
            return False

        # Champion defeated
        if not self.check_champion_defeated():
            return False

        # Complete pokedex
        caught_count = self.get_caught_count()
        return caught_count >= self.config.max_pokemon

    # === HM DETECTION ===
    # HM items are stored in the player's bag
    # Gen 1/2: Items at 0xD31D+ (2 bytes each: ID, quantity)
    # Gen 3: Items in WRAM at 0x02025xxx

    # HM Item IDs by generation
    HM_ITEMS = {
        1: {  # Gen 1 (Red/Blue/Yellow)
            "cut": 0xC4,      # 196
            "fly": 0xC5,      # 197
            "surf": 0xC6,     # 198
            "strength": 0xC7, # 199
            "flash": 0xC8,    # 200
        },
        2: {  # Gen 2 (Gold/Silver/Crystal)
            "cut": 0xF1,      # 241
            "fly": 0xF2,      # 242
            "surf": 0xF3,     # 243
            "strength": 0xF4, # 244
            "flash": 0xF5,    # 245
            "whirlpool": 0xF6,# 246
            "waterfall": 0xF7,# 247
        },
        3: {  # Gen 3 (Ruby/Sapphire/Emerald/FireRed/LeafGreen)
            "cut": 0x015E,      # 350
            "fly": 0x015F,      # 351
            "surf": 0x0160,     # 352
            "strength": 0x0161, # 353
            "flash": 0x0162,    # 354
            "rock_smash": 0x0163, # 355
            "waterfall": 0x0164,  # 356
            "dive": 0x0165,       # 357
        }
    }

    def check_has_hm(self, hm_name: str) -> bool:
        """Check if player has a specific HM in their bag"""
        if not self.config:
            return False

        gen = self.config.generation
        hm_items = self.HM_ITEMS.get(gen, {})
        hm_id = hm_items.get(hm_name.lower())

        if not hm_id:
            return False

        # Search bag for HM item
        if gen == 1:
            return self._check_bag_gen1(hm_id)
        elif gen == 2:
            return self._check_bag_gen2(hm_id)
        elif gen == 3:
            return self._check_bag_gen3(hm_id)

        return False

    def _check_bag_gen1(self, item_id: int) -> bool:
        """Check if item exists in Gen 1 bag"""
        # Gen 1 bag starts at 0xD31D
        # First byte is item count, then 2 bytes per item (ID, quantity)
        bag_start = 0xD31D

        # Read item count
        count = self.read_memory(hex(bag_start))
        if count is None or count > 20:
            return False

        # Search through items
        for i in range(min(count, 20)):
            item_addr = bag_start + 1 + (i * 2)
            item_byte = self.read_memory(hex(item_addr))
            if item_byte == item_id:
                return True

        return False

    def _check_bag_gen2(self, item_id: int) -> bool:
        """Check if item exists in Gen 2 bag"""
        # Gen 2 bag structure similar to Gen 1
        # Items start at 0xD892 (different from Gen 1)
        bag_start = 0xD892

        count = self.read_memory(hex(bag_start))
        if count is None or count > 20:
            return False

        for i in range(min(count, 20)):
            item_addr = bag_start + 1 + (i * 2)
            item_byte = self.read_memory(hex(item_addr))
            if item_byte == item_id:
                return True

        return False

    def _check_bag_gen3(self, item_id: int) -> bool:
        """Check if item exists in Gen 3 bag (GBA WRAM)"""
        # Gen 3 items are in WRAM
        # FireRed/LeafGreen: 0x02025E9C (items pocket)
        # Ruby/Sapphire/Emerald: 0x02025A94 (items pocket)

        # Try FireRed/LeafGreen address first
        bag_start_fr = 0x02025E9C
        count = self.read_memory(hex(bag_start_fr))

        if count is not None and count <= 42:
            # Search FireRed bag
            for i in range(min(count, 42)):
                # Gen 3 items are 2 bytes each (little endian)
                addr_low = bag_start_fr + 4 + (i * 4)
                addr_high = addr_low + 1
                item_low = self.read_memory(hex(addr_low))
                item_high = self.read_memory(hex(addr_high))
                if item_low is not None and item_high is not None:
                    item_value = item_low + (item_high << 8)
                    if item_value == item_id:
                        return True

        # Try Ruby/Sapphire/Emerald address
        bag_start_rse = 0x02025A94
        count = self.read_memory(hex(bag_start_rse))

        if count is not None and count <= 42:
            for i in range(min(count, 42)):
                addr_low = bag_start_rse + 4 + (i * 4)
                addr_high = addr_low + 1
                item_low = self.read_memory(hex(addr_low))
                item_high = self.read_memory(hex(addr_high))
                if item_low is not None and item_high is not None:
                    item_value = item_low + (item_high << 8)
                    if item_value == item_id:
                        return True

        return False


# === ACHIEVEMENT TEMPLATES BY GENERATION ===

def get_achievement_template(generation: int, game_name: str) -> List[dict]:
    """Generate achievement template for a game based on its generation"""

    prefix = game_name.lower().replace(" ", "_").replace("'", "")

    # Special case: FireRed/LeafGreen are Gen 3 platform but Kanto region (Gen 1)
    is_kanto_remake = game_name in ["Pokemon FireRed", "Pokemon LeafGreen"]

    # Determine region and max Pokemon
    if is_kanto_remake or generation == 1:
        region_name = "Kanto"
        max_pokemon = 151
        actual_generation = 1  # For legendary selection
    elif generation == 2:
        region_name = "Johto"
        max_pokemon = 251
        actual_generation = 2
    else:  # Gen 3 proper (Ruby/Sapphire/Emerald)
        region_name = "Hoenn"
        max_pokemon = 202  # Ruby/Sapphire/Emerald have 202 Hoenn dex
        actual_generation = 3

    # Common achievements for all games
    achievements = [
        # Story
        {
            "id": f"{prefix}_starter_chosen",
            "name": "The Journey Begins",
            "description": "Choose your starter Pokemon",
            "category": "story",
            "icon": "starter.png",
            "target_value": 1,
            "rarity": "common",
            "points": 10
            # No memory_address - derived from _check_first_steps
        },
        {
            "id": f"{prefix}_first_steps",
            "name": "First Steps",
            "description": "Begin your Pokemon journey",
            "category": "story",
            "icon": "first_steps.png",
            "target_value": 1,
            "rarity": "common",
            "points": 5
            # No memory_address - derived
        },
    ]
    
    # Story achievements - generation specific
    if actual_generation == 1:
        # Gen 1 / Kanto story achievements
        achievements.extend([
            {
                "id": f"{prefix}_story_pokedex_obtained",
                "name": "Research Assistant",
                "description": "Receive the Pokedex from Professor Oak",
                "category": "story",
                "icon": "story_pokedex.png",
                "target_value": 1,
                "rarity": "common",
                "memory_address": "0xD74B",  # wOaksLabCurScript - Pokedex obtained flag
                "memory_condition": "> 2",
                "points": 15
            },
            {
                "id": f"{prefix}_story_parcel_delivered",
                "name": "Special Delivery",
                "description": "Deliver Oak's Parcel to Professor Oak",
                "category": "story",
                "icon": "story_parcel.png",
                "target_value": 1,
                "rarity": "common",
                "memory_address": "0xD74B",  # wOaksLabCurScript - parcel delivered
                "memory_condition": "> 4",
                "points": 15
            },
            {
                "id": f"{prefix}_story_fuji_rescued",
                "name": "Tower Hero",
                "description": "Rescue Mr. Fuji from Team Rocket at Pokemon Tower",
                "category": "story",
                "icon": "story_fuji.png",
                "target_value": 1,
                "rarity": "rare",
                "memory_address": "0xD7A3",  # wLavenderTownCurScript
                "memory_condition": "> 4",
                "points": 50
            },
            {
                "id": f"{prefix}_story_silph_saved",
                "name": "Corporate Savior",
                "description": "Defeat Giovanni and save Silph Co",
                "category": "story",
                "icon": "story_silph.png",
                "target_value": 1,
                "rarity": "epic",
                "memory_address": "0xD839",  # wSilphCo9FCurScript - Giovanni defeated
                "memory_condition": "> 4",
                "points": 75
            },
            {
                "id": f"{prefix}_story_hm_cut",
                "name": "Cutting Edge",
                "description": "Obtain HM01 Cut from the Captain on the S.S. Anne",
                "category": "story",
                "icon": "story_cut.png",
                "target_value": 1,
                "rarity": "common",
                # HM detection via item - derived check needed
                "points": 20
            },
            {
                "id": f"{prefix}_story_hm_fly",
                "name": "Wings of Freedom",
                "description": "Obtain HM02 Fly from the Route 16 gatekeeper",
                "category": "story",
                "icon": "story_fly.png",
                "target_value": 1,
                "rarity": "uncommon",
                # HM detection via item
                "points": 25
            },
            {
                "id": f"{prefix}_story_hm_surf",
                "name": "Surfer Dude",
                "description": "Obtain HM03 Surf from the Secret House in Safari Zone",
                "category": "story",
                "icon": "story_surf.png",
                "target_value": 1,
                "rarity": "rare",
                # HM detection via item
                "points": 30
            },
            {
                "id": f"{prefix}_story_hm_strength",
                "name": "Strong Foundation",
                "description": "Obtain HM04 Strength from the Safari Zone warden",
                "category": "story",
                "icon": "story_strength.png",
                "target_value": 1,
                "rarity": "uncommon",
                # HM detection via item
                "points": 25
            },
        ])
    elif actual_generation == 2:
        # Gen 2 / Johto story achievements
        achievements.extend([
            {
                "id": f"{prefix}_story_pokedex_obtained",
                "name": "Research Assistant",
                "description": "Receive the Pokedex from Professor Oak",
                "category": "story",
                "icon": "story_pokedex.png",
                "target_value": 1,
                "rarity": "common",
                "memory_address": "0xD74B",  # Similar to Gen 1
                "memory_condition": "> 0",
                "points": 15
            },
            {
                "id": f"{prefix}_story_rival_first",
                "name": "First Blood",
                "description": "Defeat your rival for the first time",
                "category": "story",
                "icon": "story_rival.png",
                "target_value": 1,
                "rarity": "common",
                "memory_address": "0xD74C",  # wRoute22CurScript - first rival battle
                "memory_condition": "> 2",
                "points": 15
            },
            {
                "id": f"{prefix}_story_team_rocket_hideout",
                "name": "Hideout Hunter",
                "description": "Clear the Team Rocket Hideout in Mahogany Town",
                "category": "story",
                "icon": "story_rocket.png",
                "target_value": 1,
                "rarity": "rare",
                "memory_address": "0xD84A",  # Team Rocket event flags
                "memory_condition": "& 0x01",
                "points": 50
            },
            {
                "id": f"{prefix}_story_radio_tower",
                "name": "Airwave Liberator",
                "description": "Rescue the Radio Tower from Team Rocket",
                "category": "story",
                "icon": "story_radio.png",
                "target_value": 1,
                "rarity": "epic",
                "memory_address": "0xD84A",
                "memory_condition": "& 0x02",
                "points": 75
            },
            {
                "id": f"{prefix}_story_elite_four_access",
                "name": "Victory Road Access",
                "description": "Gain access to the Elite Four at Indigo Plateau",
                "category": "story",
                "icon": "story_e4access.png",
                "target_value": 1,
                "rarity": "rare",
                "memory_address": "0xD74E",  # Elite Four access flag
                "memory_condition": "> 0",
                "points": 40
            },
        ])
    else:
        # Gen 3 / Hoenn story achievements
        achievements.extend([
            {
                "id": f"{prefix}_story_pokedex_obtained",
                "name": "Research Assistant",
                "description": "Receive the Pokedex from Professor Birch",
                "category": "story",
                "icon": "story_pokedex.png",
                "target_value": 1,
                "rarity": "common",
                "memory_address": "0x02024A64",  # GBA script progress
                "memory_condition": "> 10",
                "points": 15
            },
            {
                "id": f"{prefix}_story_weather_institute",
                "name": "Weather Savior",
                "description": "Rescue the Weather Institute from Team Aqua/Magma",
                "category": "story",
                "icon": "story_weather.png",
                "target_value": 1,
                "rarity": "uncommon",
                "memory_address": "0x02024A68",  # Weather Institute event
                "memory_condition": "> 0",
                "points": 35
            },
            {
                "id": f"{prefix}_story_mt_chimney",
                "name": "Mountain Defender",
                "description": "Defeat Team Aqua/Magma at Mt. Chimney",
                "category": "story",
                "icon": "story_chimney.png",
                "target_value": 1,
                "rarity": "rare",
                "memory_address": "0x02024A6C",  # Mt. Chimney event
                "memory_condition": "> 0",
                "points": 50
            },
            {
                "id": f"{prefix}_story_space_center",
                "name": "Space Guardian",
                "description": "Defend the Mossdeep Space Center",
                "category": "story",
                "icon": "story_space.png",
                "target_value": 1,
                "rarity": "epic",
                "memory_address": "0x02024A70",  # Space Center event
                "memory_condition": "> 0",
                "points": 75
            },
            {
                "id": f"{prefix}_story_cave_of_origin",
                "name": "Primal Awakening",
                "description": "Enter the Cave of Origin",
                "category": "story",
                "icon": "story_cave.png",
                "target_value": 1,
                "rarity": "epic",
                "memory_address": "0x02024A74",
                "memory_condition": "> 0",
                "points": 60
            },
        ])

    # Pokedex achievements
    pokedex_targets = [10, 25, 50, 100]
    pokedex_names = ["Junior Researcher", "Collector", "Pokemon Enthusiast", "Pokedex Master"]

    for target, name in zip(pokedex_targets, pokedex_names):
        achievements.append({
            "id": f"{prefix}_pokedex_{target}",
            "name": name,
            "description": f"Register {target} Pokemon in the Pokedex",
            "category": "pokedex",
            "icon": f"pokedex_{target}.png",
            "target_value": target,
            "rarity": "common" if target < 50 else ("uncommon" if target < 100 else "rare"),
            "points": target
            # No memory_address - derived from Pokedex count
        })

    # Completion achievement (use already calculated values)
    achievements.append({
        "id": f"{prefix}_pokedex_complete",
        "name": f"{region_name} Completionist",
        "description": f"Complete the {region_name} Pokedex ({max_pokemon} Pokemon)",
        "category": "pokedex",
        "icon": "pokedex_complete.png",
        "target_value": max_pokemon,
        "rarity": "epic",
        "points": 500
        # No memory_address - derived
    })

    # Gym badges - will have memory_address set by game-specific config
    gym_leaders = {
        1: ["Brock", "Misty", "Lt. Surge", "Erika", "Koga", "Sabrina", "Blaine", "Giovanni"],
        2: ["Falkner", "Bugsy", "Whitney", "Morty", "Chuck", "Jasmine", "Pryce", "Clair"],
        3: ["Roxanne", "Brawly", "Wattson", "Flannery", "Norman", "Winona", "Tate & Liza", "Juan/Wallace"]
    }

    gym_badges = {
        1: ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"],
        2: ["Zephyr", "Hive", "Plain", "Fog", "Storm", "Mineral", "Glacier", "Rising"],
        3: ["Stone", "Knuckle", "Dynamo", "Heat", "Balance", "Feather", "Mind", "Rain"]
    }

    leaders = gym_leaders.get(actual_generation, gym_leaders[1])
    badges = gym_badges.get(actual_generation, gym_badges[1])

    for i, (leader, badge) in enumerate(zip(leaders, badges)):
        achievements.append({
            "id": f"{prefix}_gym_{i+1}_{leader.lower().replace(' ', '_').replace('&', 'and')}",
            "name": f"{badge} Badge",
            "description": f"Defeat {leader} and earn the {badge} Badge",
            "category": "gym",
            "icon": f"gym_{i+1}.png",
            "target_value": 1,
            "rarity": "common",
            "memory_address": "DERIVED",  # Will be replaced with actual address
            "memory_condition": f"& {hex(1 << i)}",
            "points": 25
        })

    # All gyms - derived
    achievements.append({
        "id": f"{prefix}_gym_all",
        "name": "Gym Leader Conqueror",
        "description": "Defeat all 8 Gym Leaders",
        "category": "gym",
        "icon": "gym_all.png",
        "target_value": 8,
        "rarity": "rare",
        "points": 100
        # No memory_address - derived
    })

    # Elite Four - generation specific (use actual_generation for region)
    if actual_generation == 1:
        e4_members = ["Lorelei", "Bruno", "Agatha", "Lance"]
    elif actual_generation == 2:
        e4_members = ["Will", "Koga", "Bruno", "Karen"]
    else:  # Gen 3
        e4_members = ["Sidney", "Phoebe", "Glacia", "Drake"]

    for member in e4_members:
        achievements.append({
            "id": f"{prefix}_elite_four_{member.lower()}",
            "name": f"Elite Four: {member}",
            "description": f"Defeat {member} of the Elite Four",
            "category": "elite_four",
            "icon": f"e4_{member.lower()}.png",
            "target_value": 1,
            "rarity": "rare",
            "points": 50
            # No memory_address - derived
        })

    # All Elite Four - derived
    achievements.append({
        "id": f"{prefix}_elite_four_all",
        "name": "Elite Four Vanquisher",
        "description": "Defeat all members of the Elite Four",
        "category": "elite_four",
        "icon": "e4_all.png",
        "target_value": 4,
        "rarity": "epic",
        "points": 200
        # No memory_address - derived
    })

    # Champion (use actual_generation for region)
    champion_name = "Blue" if actual_generation == 1 else ("Lance" if actual_generation == 2 else "Steven")
    achievements.append({
        "id": f"{prefix}_champion_{champion_name.lower()}",
        "name": f"Champion Slayer: {champion_name}",
        "description": f"Defeat Champion {champion_name}",
        "category": "champion",
        "icon": "champion.png",
        "target_value": 1,
        "rarity": "epic",
        "memory_address": "DERIVED",
        "memory_condition": "> 0",
        "points": 300
    })

    # Legendary achievements - generation specific (use actual_generation!)
    legendaries = {
        1: [("mewtwo", "Mewtwo"), ("moltres", "Moltres"), ("zapdos", "Zapdos"), ("articuno", "Articuno")],
        2: [("lugia", "Lugia"), ("ho-oh", "Ho-Oh"), ("suicune", "Suicune"), ("entei", "Entei"), ("raikou", "Raikou")],
        3: [("kyogre", "Kyogre"), ("groudon", "Groudon"), ("rayquaza", "Rayquaza"),
             ("latias", "Latias"), ("latios", "Latios"), ("regirock", "Regirock"),
             ("regice", "Regice"), ("registeel", "Registeel")]
    }

    for legendary_id, legendary_name in legendaries.get(actual_generation, []):
        achievements.append({
            "id": f"{prefix}_legendary_{legendary_id}",
            "name": f"Legendary Caught: {legendary_name}",
            "description": f"Catch the legendary Pokemon {legendary_name}",
            "category": "legendary",
            "icon": f"legendary_{legendary_id}.png",
            "target_value": 1,
            "rarity": "epic",
            "points": 150
            # No memory_address - derived from Pokedex
        })

    # Legendary collection achievements
    if actual_generation == 1:
        achievements.append({
            "id": f"{prefix}_legendary_birds",
            "name": "Winged Legends",
            "description": "Catch Articuno, Zapdos, and Moltres",
            "category": "legendary",
            "icon": "legendary_birds.png",
            "target_value": 3,
            "rarity": "epic",
            "points": 400
        })

    achievements.append({
        "id": f"{prefix}_legendary_all",
        "name": "Legendary Master",
        "description": "Catch all legendary Pokemon in the game",
        "category": "legendary",
        "icon": "legendary_master.png",
        "target_value": len(legendaries.get(actual_generation, [])),
        "rarity": "legendary",
        "points": 1000
    })

    # Pokemon Master - ultimate achievement
    achievements.append({
        "id": f"{prefix}_pokemon_master",
        "name": "Pokemon Master",
        "description": f"All badges, Champion defeated, and complete {region_name} Pokedex",
        "category": "master",
        "icon": "pokemon_master.png",
        "target_value": 1,
        "rarity": "legendary",
        "points": 5000
        # No memory_address - derived
    })

    return achievements


if __name__ == "__main__":
    # Test generate templates
    import json

    for game in ["Pokemon Red", "Pokemon Emerald", "Pokemon Crystal"]:
        gen = get_generation(game)
        template = get_achievement_template(gen, game)
        print(f"\n=== {game} (Gen {gen}) ===")
        print(f"Total achievements: {len(template)}")
        print(f"Memory config: {get_game_config(game)}")
