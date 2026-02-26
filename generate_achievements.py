#!/usr/bin/env python3
"""
Achievement JSON Generator & Validator for PokeAchieve
Generates properly configured achievement files for all supported games
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Import the game configs
sys.path.insert(0, str(Path(__file__).parent))
from game_configs import (
    get_game_config, get_generation, get_platform,
    get_achievement_template, GAME_CONFIGS
)


# Game-specific memory address overrides
# These fill in the "DERIVED" placeholders with actual addresses
GAME_MEMORY_OVERRIDES = {
    "Pokemon Red": {
        # Badge flags at 0xD356, each bit is a badge
        "red_gym_1_brock": {"memory_address": "0xD356", "memory_condition": "& 0x01"},
        "red_gym_2_misty": {"memory_address": "0xD356", "memory_condition": "& 0x02"},
        "red_gym_3_lt_surge": {"memory_address": "0xD356", "memory_condition": "& 0x04"},
        "red_gym_4_erika": {"memory_address": "0xD356", "memory_condition": "& 0x08"},
        "red_gym_5_koga": {"memory_address": "0xD356", "memory_condition": "& 0x10"},
        "red_gym_6_sabrina": {"memory_address": "0xD356", "memory_condition": "& 0x20"},
        "red_gym_7_blaine": {"memory_address": "0xD356", "memory_condition": "& 0x40"},
        "red_gym_8_giovanni": {"memory_address": "0xD356", "memory_condition": "& 0x80"},
        "red_champion_blue": {"memory_address": "0xD357", "memory_condition": "& 0x01"},
    },
    "Pokemon Blue": {
        # Same as Red
        "blue_gym_1_brock": {"memory_address": "0xD356", "memory_condition": "& 0x01"},
        "blue_gym_2_misty": {"memory_address": "0xD356", "memory_condition": "& 0x02"},
        "blue_gym_3_lt_surge": {"memory_address": "0xD356", "memory_condition": "& 0x04"},
        "blue_gym_4_erika": {"memory_address": "0xD356", "memory_condition": "& 0x08"},
        "blue_gym_5_koga": {"memory_address": "0xD356", "memory_condition": "& 0x10"},
        "blue_gym_6_sabrina": {"memory_address": "0xD356", "memory_condition": "& 0x20"},
        "blue_gym_7_blaine": {"memory_address": "0xD356", "memory_condition": "& 0x40"},
        "blue_gym_8_giovanni": {"memory_address": "0xD356", "memory_condition": "& 0x80"},
        "blue_champion_blue": {"memory_address": "0xD357", "memory_condition": "& 0x01"},
    },
    "Pokemon Gold": {
        # Gen 2 badge address is 0xD35C
        "gold_gym_1_falkner": {"memory_address": "0xD35C", "memory_condition": "& 0x01"},
        "gold_gym_2_bugsy": {"memory_address": "0xD35C", "memory_condition": "& 0x02"},
        "gold_gym_3_whitney": {"memory_address": "0xD35C", "memory_condition": "& 0x04"},
        "gold_gym_4_morty": {"memory_address": "0xD35C", "memory_condition": "& 0x08"},
        "gold_gym_5_chuck": {"memory_address": "0xD35C", "memory_condition": "& 0x10"},
        "gold_gym_6_jasmine": {"memory_address": "0xD35C", "memory_condition": "& 0x20"},
        "gold_gym_7_pryce": {"memory_address": "0xD35C", "memory_condition": "& 0x40"},
        "gold_gym_8_clair": {"memory_address": "0xD35C", "memory_condition": "& 0x80"},
        "gold_champion_lance": {"memory_address": "0xD6E8", "memory_condition": "> 0"},
    },
    "Pokemon Silver": {
        # Same as Gold
        "silver_gym_1_falkner": {"memory_address": "0xD35C", "memory_condition": "& 0x01"},
        "silver_gym_2_bugsy": {"memory_address": "0xD35C", "memory_condition": "& 0x02"},
        "silver_gym_3_whitney": {"memory_address": "0xD35C", "memory_condition": "& 0x04"},
        "silver_gym_4_morty": {"memory_address": "0xD35C", "memory_condition": "& 0x08"},
        "silver_gym_5_chuck": {"memory_address": "0xD35C", "memory_condition": "& 0x10"},
        "silver_gym_6_jasmine": {"memory_address": "0xD35C", "memory_condition": "& 0x20"},
        "silver_gym_7_pryce": {"memory_address": "0xD35C", "memory_condition": "& 0x40"},
        "silver_gym_8_clair": {"memory_address": "0xD35C", "memory_condition": "& 0x80"},
        "silver_champion_lance": {"memory_address": "0xD6E8", "memory_condition": "> 0"},
    },
    "Pokemon Crystal": {
        # Same as Gold/Silver
        "crystal_gym_1_falkner": {"memory_address": "0xD35C", "memory_condition": "& 0x01"},
        "crystal_gym_2_bugsy": {"memory_address": "0xD35C", "memory_condition": "& 0x02"},
        "crystal_gym_3_whitney": {"memory_address": "0xD35C", "memory_condition": "& 0x04"},
        "crystal_gym_4_morty": {"memory_address": "0xD35C", "memory_condition": "& 0x08"},
        "crystal_gym_5_chuck": {"memory_address": "0xD35C", "memory_condition": "& 0x10"},
        "crystal_gym_6_jasmine": {"memory_address": "0xD35C", "memory_condition": "& 0x20"},
        "crystal_gym_7_pryce": {"memory_address": "0xD35C", "memory_condition": "& 0x40"},
        "crystal_gym_8_clair": {"memory_address": "0xD35C", "memory_condition": "& 0x80"},
        "crystal_champion_lance": {"memory_address": "0xD6E8", "memory_condition": "> 0"},
    },
    "Pokemon Ruby": {
        # Gen 3 uses GBA WRAM addresses
        "ruby_gym_1_roxanne": {"memory_address": "0x02024A6C", "memory_condition": "& 0x01"},
        "ruby_gym_2_brawly": {"memory_address": "0x02024A6C", "memory_condition": "& 0x02"},
        "ruby_gym_3_wattson": {"memory_address": "0x02024A6C", "memory_condition": "& 0x04"},
        "ruby_gym_4_flannery": {"memory_address": "0x02024A6C", "memory_condition": "& 0x08"},
        "ruby_gym_5_norman": {"memory_address": "0x02024A6C", "memory_condition": "& 0x10"},
        "ruby_gym_6_winona": {"memory_address": "0x02024A6C", "memory_condition": "& 0x20"},
        "ruby_gym_7_tate_and_liza": {"memory_address": "0x02024A6C", "memory_condition": "& 0x40"},
        "ruby_gym_8_juan": {"memory_address": "0x02024A6C", "memory_condition": "& 0x80"},
        "ruby_champion_steven": {"memory_address": "0x02024A70", "memory_condition": "> 0"},
    },
    "Pokemon Sapphire": {
        # Same as Ruby
        "sapphire_gym_1_roxanne": {"memory_address": "0x02024A6C", "memory_condition": "& 0x01"},
        "sapphire_gym_2_brawly": {"memory_address": "0x02024A6C", "memory_condition": "& 0x02"},
        "sapphire_gym_3_wattson": {"memory_address": "0x02024A6C", "memory_condition": "& 0x04"},
        "sapphire_gym_4_flannery": {"memory_address": "0x02024A6C", "memory_condition": "& 0x08"},
        "sapphire_gym_5_norman": {"memory_address": "0x02024A6C", "memory_condition": "& 0x10"},
        "sapphire_gym_6_winona": {"memory_address": "0x02024A6C", "memory_condition": "& 0x20"},
        "sapphire_gym_7_tate_and_liza": {"memory_address": "0x02024A6C", "memory_condition": "& 0x40"},
        "sapphire_gym_8_juan": {"memory_address": "0x02024A6C", "memory_condition": "& 0x80"},
        "sapphire_champion_steven": {"memory_address": "0x02024A70", "memory_condition": "> 0"},
    },
    "Pokemon Emerald": {
        # Same memory layout as Ruby/Sapphire
        "emerald_gym_1_roxanne": {"memory_address": "0x02024A6C", "memory_condition": "& 0x01"},
        "emerald_gym_2_brawly": {"memory_address": "0x02024A6C", "memory_condition": "& 0x02"},
        "emerald_gym_3_wattson": {"memory_address": "0x02024A6C", "memory_condition": "& 0x04"},
        "emerald_gym_4_flannery": {"memory_address": "0x02024A6C", "memory_condition": "& 0x08"},
        "emerald_gym_5_norman": {"memory_address": "0x02024A6C", "memory_condition": "& 0x10"},
        "emerald_gym_6_winona": {"memory_address": "0x02024A6C", "memory_condition": "& 0x20"},
        "emerald_gym_7_tate_and_liza": {"memory_address": "0x02024A6C", "memory_condition": "& 0x40"},
        "emerald_gym_8_juan": {"memory_address": "0x02024A6C", "memory_condition": "& 0x80"},
        "emerald_champion_steven": {"memory_address": "0x02024A70", "memory_condition": "> 0"},
    },
    "Pokemon FireRed": {
        # FRLG on GBA - different from Ruby/Emerald
        "firered_gym_1_brock": {"memory_address": "0x02024A6C", "memory_condition": "& 0x01"},
        "firered_gym_2_misty": {"memory_address": "0x02024A6C", "memory_condition": "& 0x02"},
        "firered_gym_3_lt_surge": {"memory_address": "0x02024A6C", "memory_condition": "& 0x04"},
        "firered_gym_4_erika": {"memory_address": "0x02024A6C", "memory_condition": "& 0x08"},
        "firered_gym_5_koga": {"memory_address": "0x02024A6C", "memory_condition": "& 0x10"},
        "firered_gym_6_sabrina": {"memory_address": "0x02024A6C", "memory_condition": "& 0x20"},
        "firered_gym_7_blaine": {"memory_address": "0x02024A6C", "memory_condition": "& 0x40"},
        "firered_gym_8_giovanni": {"memory_address": "0x02024A6C", "memory_condition": "& 0x80"},
        "firered_champion_blue": {"memory_address": "0x02024A70", "memory_condition": "> 0"},
    },
    "Pokemon LeafGreen": {
        # Same as FireRed
        "leafgreen_gym_1_brock": {"memory_address": "0x02024A6C", "memory_condition": "& 0x01"},
        "leafgreen_gym_2_misty": {"memory_address": "0x02024A6C", "memory_condition": "& 0x02"},
        "leafgreen_gym_3_lt_surge": {"memory_address": "0x02024A6C", "memory_condition": "& 0x04"},
        "leafgreen_gym_4_erika": {"memory_address": "0x02024A6C", "memory_condition": "& 0x08"},
        "leafgreen_gym_5_koga": {"memory_address": "0x02024A6C", "memory_condition": "& 0x10"},
        "leafgreen_gym_6_sabrina": {"memory_address": "0x02024A6C", "memory_condition": "& 0x20"},
        "leafgreen_gym_7_blaine": {"memory_address": "0x02024A6C", "memory_condition": "& 0x40"},
        "leafgreen_gym_8_giovanni": {"memory_address": "0x02024A6C", "memory_condition": "& 0x80"},
        "leafgreen_champion_blue": {"memory_address": "0x02024A70", "memory_condition": "> 0"},
    },
}


def generate_game_achievements(game_name: str) -> dict:
    """Generate complete achievement configuration for a game"""
    gen = get_generation(game_name)
    platform = get_platform(game_name)
    config = get_game_config(game_name)
    
    # Get base template
    achievements = get_achievement_template(gen, game_name)
    
    # Apply memory address overrides
    overrides = GAME_MEMORY_OVERRIDES.get(game_name, {})
    
    for ach in achievements:
        ach_id = ach["id"]
        if ach_id in overrides:
            ach["memory_address"] = overrides[ach_id]["memory_address"]
            ach["memory_condition"] = overrides[ach_id]["memory_condition"]
        elif ach.get("memory_address") == "DERIVED":
            # Remove placeholder - these are derived achievements
            del ach["memory_address"]
            if "memory_condition" in ach:
                del ach["memory_condition"]
    
    return {
        "game": {
            "name": game_name,
            "platform": platform,
            "generation": gen,
            "memory_config": {
                "pokedex_caught_start": config.pokedex_caught_start if config else None,
                "badge_address": config.badge_address if config else None,
                "party_count_address": config.party_count_address if config else None,
            }
        },
        "achievements": achievements
    }


def validate_existing_json(filepath: Path) -> tuple[bool, List[str]]:
    """Validate an existing achievement JSON file"""
    errors = []
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    except Exception as e:
        return False, [f"Error reading file: {e}"]
    
    # Check required fields
    if "game" not in data:
        errors.append("Missing 'game' section")
    else:
        game = data["game"]
        if "name" not in game:
            errors.append("Missing game.name")
        if "platform" not in game:
            errors.append("Missing game.platform")
    
    if "achievements" not in data:
        errors.append("Missing 'achievements' array")
    else:
        achievements = data["achievements"]
        
        # Check for required achievement fields
        required = ["id", "name", "description", "category", "points"]
        
        for i, ach in enumerate(achievements):
            for field in required:
                if field not in ach:
                    errors.append(f"Achievement[{i}] missing '{field}'")
            
            # Check for proper memory configuration
            has_address = "memory_address" in ach and ach["memory_address"]
            is_derived = not has_address  # Derived achievements have no memory_address
            
            if has_address and "memory_condition" not in ach:
                errors.append(f"Achievement[{i}] '{ach.get('id', 'unknown')}' has memory_address but no memory_condition")
    
    return len(errors) == 0, errors


def generate_all_games(output_dir: Path, dry_run: bool = False):
    """Generate achievement files for all supported games"""
    
    games = [
        "Pokemon Red",
        "Pokemon Blue",
        "Pokemon Gold",
        "Pokemon Silver",
        "Pokemon Crystal",
        "Pokemon Ruby",
        "Pokemon Sapphire",
        "Pokemon Emerald",
        "Pokemon FireRed",
        "Pokemon LeafGreen",
    ]
    
    results = []
    
    for game in games:
        prefix = game.lower().replace(" ", "_").replace("'", "")
        filename = f"{prefix}.json"
        filepath = output_dir / filename
        
        data = generate_game_achievements(game)
        
        if dry_run:
            results.append({
                "game": game,
                "filename": filename,
                "achievements": len(data["achievements"]),
                "would_write": not filepath.exists()
            })
        else:
            # Backup existing file
            if filepath.exists():
                backup_path = filepath.with_suffix('.json.backup')
                filepath.rename(backup_path)
                print(f"  Backed up: {filepath.name} -> {backup_path.name}")
            
            # Write new file
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            results.append({
                "game": game,
                "filename": filename,
                "achievements": len(data["achievements"]),
                "written": True
            })
            print(f"  Generated: {filepath.name} ({len(data['achievements'])} achievements)")
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate and validate PokeAchieve achievement files")
    parser.add_argument("--output-dir", "-o", type=Path, default=Path("achievements/games"),
                        help="Output directory for achievement files")
    parser.add_argument("--validate", "-v", type=Path, metavar="FILE",
                        help="Validate an existing achievement JSON file")
    parser.add_argument("--generate", "-g", action="store_true",
                        help="Generate all achievement files")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be generated without writing files")
    parser.add_argument("--game", type=str,
                        help="Generate for a specific game only")
    
    args = parser.parse_args()
    
    if args.validate:
        valid, errors = validate_existing_json(args.validate)
        if valid:
            print(f"✅ {args.validate} is valid")
        else:
            print(f"❌ {args.validate} has errors:")
            for err in errors:
                print(f"   - {err}")
        return 0 if valid else 1
    
    if args.generate or args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        
        if args.dry_run:
            print(f"Dry run - would generate files in: {args.output_dir}")
        else:
            print(f"Generating achievement files in: {args.output_dir}")
        
        if args.game:
            # Generate for specific game
            data = generate_game_achievements(args.game)
            prefix = args.game.lower().replace(" ", "_").replace("'", "")
            filepath = args.output_dir / f"{prefix}.json"
            
            if args.dry_run:
                print(f"\nWould generate: {filepath.name}")
                print(f"  Achievements: {len(data['achievements'])}")
            else:
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"Generated: {filepath.name} ({len(data['achievements'])} achievements)")
        else:
            # Generate all games
            results = generate_all_games(args.output_dir, dry_run=args.dry_run)
            
            print(f"\n{'='*50}")
            print(f"Summary: {len(results)} games")
            total_achievements = sum(r['achievements'] for r in results)
            print(f"Total achievements: {total_achievements}")
            
            if args.dry_run:
                new_files = sum(1 for r in results if r.get('would_write'))
                print(f"New files to create: {new_files}")
        
        return 0
    
    # Default: show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
