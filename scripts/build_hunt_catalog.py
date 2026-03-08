#!/usr/bin/env python3
"""
Build hunt encounter catalog from PokeAPI for Gen 2/3 games.

Output:
  hunt_encounter_catalog.json
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set

BASE_URL = "https://pokeapi.co/api/v2"

VERSION_TO_GAME = {
    "gold": "Pokemon Gold",
    "silver": "Pokemon Silver",
    "crystal": "Pokemon Crystal",
    "ruby": "Pokemon Ruby",
    "sapphire": "Pokemon Sapphire",
    "emerald": "Pokemon Emerald",
    "firered": "Pokemon FireRed",
    "leafgreen": "Pokemon LeafGreen",
}

FISHING_METHODS = {
    "old-rod",
    "good-rod",
    "super-rod",
    "feebas-tile-fishing",
}

SURF_METHODS = {
    "surf",
    "roaming-water",
}

DIVE_METHODS = {
    "seaweed",
    "dive",
}

LAND_WILD_METHODS = {
    "walk",
    "rock-smash",
    "headbutt-low",
    "headbutt-normal",
    "headbutt-high",
    "roaming-grass",
}

SPECIAL_CASE_NAMES = {
    "digletts-cave": "Diglett's Cave",
    "mt-moon": "Mt. Moon",
    "mt-silver": "Mt. Silver",
    "mt-mortar": "Mt. Mortar",
    "mt-pyre": "Mt. Pyre",
    "seafoam-islands": "Seafoam Islands",
    "victory-road": "Victory Road",
    "pokemon-tower": "Pokemon Tower",
    "pokemon-mansion": "Pokemon Mansion",
    "power-plant": "Power Plant",
    "safari-zone": "Safari Zone",
}

REGION_PREFIXES = {"kanto", "johto", "hoenn"}


def fetch_json(url: str, retries: int = 4, timeout: int = 12) -> Optional[dict]:
    last_error = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PokeAchieveTracker/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.3 * (attempt + 1))
    print(f"fetch failed: {url} ({last_error})")
    return None


def parse_species_id(url: str) -> int:
    token = str(url).rstrip("/").split("/")[-1]
    try:
        return int(token)
    except Exception:  # noqa: BLE001
        return 0


def format_location_name(raw_name: str) -> str:
    key = str(raw_name).strip().lower()
    if key in SPECIAL_CASE_NAMES:
        return SPECIAL_CASE_NAMES[key]

    route_match = re.match(r"^(?:kanto-|johto-|hoenn-)?route-(\d+)$", key)
    if route_match:
        return f"Route {int(route_match.group(1))}"

    sea_route_match = re.match(r"^(?:kanto-|johto-|hoenn-)?sea-route-(\d+)$", key)
    if sea_route_match:
        return f"Route {int(sea_route_match.group(1))}"

    tokens = [t for t in key.split("-") if t]
    if tokens and tokens[0] in REGION_PREFIXES:
        tokens = tokens[1:]

    cooked: List[str] = []
    for token in tokens:
        if token == "mt":
            cooked.append("Mt.")
        elif token == "mr":
            cooked.append("Mr.")
        elif token == "ss":
            cooked.append("S.S.")
        elif token == "pokemon":
            cooked.append("Pokemon")
        else:
            cooked.append(token.capitalize())
    result = " ".join(cooked).strip()
    return result if result else raw_name


def sort_locations(names: List[str]) -> List[str]:
    def sort_key(value: str):
        text = str(value)
        match = re.match(r"^Route (\d+)(?: \((.+)\))?$", text)
        if match:
            variant = match.group(2) or ""
            return (0, int(match.group(1)), variant.lower())
        return (1, text.lower())

    return sorted(names, key=sort_key)


def iter_location_area_urls() -> List[str]:
    urls: List[str] = []
    next_url = f"{BASE_URL}/location-area?limit=1000&offset=0"
    while next_url:
        data = fetch_json(next_url)
        if not isinstance(data, dict):
            break
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    url = item.get("url")
                    if isinstance(url, str) and url:
                        urls.append(url)
        next_url = data.get("next") if isinstance(data.get("next"), str) else None
    return urls


def build_catalog() -> Dict[str, Dict[str, Dict[str, List[int]]]]:
    games = list(VERSION_TO_GAME.values())
    random_land: Dict[str, Dict[str, Set[int]]] = {g: {} for g in games}
    random_surf: Dict[str, Dict[str, Set[int]]] = {g: {} for g in games}
    random_dive: Dict[str, Dict[str, Set[int]]] = {g: {} for g in games}
    fishing: Dict[str, Dict[str, Set[int]]] = {g: {} for g in games}

    area_urls = iter_location_area_urls()
    print(f"location areas: {len(area_urls)}")

    def _load_area(url: str) -> Optional[dict]:
        return fetch_json(url)

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_load_area, url) for url in area_urls]
        for idx, future in enumerate(as_completed(futures), start=1):
            area = future.result()
            if not isinstance(area, dict):
                continue

            location = area.get("location")
            location_name = ""
            if isinstance(location, dict):
                location_name = str(location.get("name") or "").strip().lower()
            if not location_name:
                continue
            display_name = format_location_name(location_name)

            encounters = area.get("pokemon_encounters")
            if not isinstance(encounters, list):
                continue

            for encounter in encounters:
                if not isinstance(encounter, dict):
                    continue
                pokemon_data = encounter.get("pokemon")
                if not isinstance(pokemon_data, dict):
                    continue
                species_id = parse_species_id(str(pokemon_data.get("url") or ""))
                if species_id <= 0:
                    continue

                version_details = encounter.get("version_details")
                if not isinstance(version_details, list):
                    continue

                for version_detail in version_details:
                    if not isinstance(version_detail, dict):
                        continue
                    version = version_detail.get("version")
                    if not isinstance(version, dict):
                        continue
                    version_name = str(version.get("name") or "").strip().lower()
                    game_name = VERSION_TO_GAME.get(version_name)
                    if not game_name:
                        continue

                    encounter_details = version_detail.get("encounter_details")
                    if not isinstance(encounter_details, list):
                        continue

                    method_names: Set[str] = set()
                    for detail in encounter_details:
                        if not isinstance(detail, dict):
                            continue
                        method = detail.get("method")
                        if not isinstance(method, dict):
                            continue
                        method_name = str(method.get("name") or "").strip().lower()
                        if method_name:
                            method_names.add(method_name)

                    if not method_names:
                        continue

                    if any(m in LAND_WILD_METHODS for m in method_names):
                        random_land[game_name].setdefault(display_name, set()).add(species_id)

                    if any(m in SURF_METHODS for m in method_names):
                        random_surf[game_name].setdefault(display_name, set()).add(species_id)

                    if any(m in DIVE_METHODS for m in method_names):
                        random_dive[game_name].setdefault(display_name, set()).add(species_id)

                    if any(m in FISHING_METHODS for m in method_names):
                        fishing[game_name].setdefault(display_name, set()).add(species_id)

            if idx % 200 == 0:
                print(f"processed: {idx}/{len(area_urls)}")

    output: Dict[str, Dict[str, Dict[str, List[int]]]] = {}
    for game_name in games:
        random_entries: Dict[str, List[int]] = {}
        random_union: Set[int] = set()

        location_names = (
            set(random_land[game_name].keys())
            | set(random_surf[game_name].keys())
            | set(random_dive[game_name].keys())
        )
        for location_name in sort_locations(list(location_names)):
            land_ids = sorted(random_land[game_name].get(location_name, set()))
            surf_ids = sorted(random_surf[game_name].get(location_name, set()))
            dive_ids = sorted(random_dive[game_name].get(location_name, set()))
            if land_ids:
                random_entries[location_name] = land_ids
                random_union.update(land_ids)
            if surf_ids:
                random_entries[f"{location_name} (Surf)"] = surf_ids
                random_union.update(surf_ids)
            if dive_ids:
                random_entries[f"{location_name} (Dive)"] = dive_ids
                random_union.update(dive_ids)

        fishing_entries: Dict[str, List[int]] = {}
        fishing_union: Set[int] = set()
        for location_name in sort_locations(list(fishing[game_name].keys())):
            ids = sorted(fishing[game_name].get(location_name, set()))
            if not ids:
                continue
            fishing_entries[location_name] = ids
            fishing_union.update(ids)

        output[game_name] = {
            "random": {"Any Route / Area": sorted(random_union), **random_entries},
            "fishing": {"Any Fishing Spot": sorted(fishing_union), **fishing_entries},
            "soft_reset": {
                "Any Soft Reset": [],
                "Starters": [],
                "Trades": [],
                "Gift": [],
                "Stationary": [],
            },
        }

    return output


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    catalog = build_catalog()
    out_path = repo_root / "hunt_encounter_catalog.json"
    out_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote: {out_path}")


if __name__ == "__main__":
    main()
