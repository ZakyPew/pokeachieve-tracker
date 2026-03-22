#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class BattleSceneSource:
    game: str
    slug: str
    image_url: str
    source_page: str


SCENE_SOURCES: List[BattleSceneSource] = [
    BattleSceneSource(
        game="Pokemon Red",
        slug="pokemon_red",
        image_url="https://cdn.mobygames.com/screenshots/15654856-pokemon-red-version-game-boy-pokemon-appear-in-the-wild-when-you.png",
        source_page="https://www.mobygames.com/game/5129/pokemon-red-version/screenshots/gameboy/356897/",
    ),
    BattleSceneSource(
        game="Pokemon Blue",
        slug="pokemon_blue",
        image_url="https://cdn.mobygames.com/screenshots/15654876-pokemon-blue-version-game-boy-pokemon-appear-in-the-wild-when-yo.png",
        source_page="https://www.mobygames.com/game/4397/pokemon-blue-version/screenshots/gameboy/177456/",
    ),
    BattleSceneSource(
        game="Pokemon Gold",
        slug="pokemon_gold",
        image_url="https://cdn.mobygames.com/screenshots/16870458-pokemon-gold-version-game-boy-color-fighting-pokemon.png",
        source_page="https://www.mobygames.com/game/5427/pokemon-gold-version/screenshots/gameboy-color/59848/",
    ),
    BattleSceneSource(
        game="Pokemon Silver",
        slug="pokemon_silver",
        image_url="https://cdn.mobygames.com/screenshots/16870513-pokemon-silver-version-game-boy-color-i-dont-want-to-die.png",
        source_page="https://www.mobygames.com/game/5429/pokemon-silver-version/screenshots/gameboy-color/59871/",
    ),
    BattleSceneSource(
        game="Pokemon Crystal",
        slug="pokemon_crystal",
        image_url="https://cdn.mobygames.com/screenshots/564730-pokemon-crystal-version-game-boy-color-your-usual-battle-screen.png",
        source_page="https://www.mobygames.com/game/5428/pokemon-crystal-version/screenshots/gameboy-color/268800/",
    ),
    BattleSceneSource(
        game="Pokemon Ruby",
        slug="pokemon_ruby",
        image_url="https://cdn.mobygames.com/screenshots/18320995-pokemon-ruby-version-game-boy-advance-giving-my-rival-a-beatdown.png",
        source_page="https://www.mobygames.com/game/13769/pokemon-ruby-version/screenshots/gameboy-advance/616527/",
    ),
    BattleSceneSource(
        game="Pokemon Sapphire",
        slug="pokemon_sapphire",
        image_url="https://cdn.mobygames.com/screenshots/16976016-pokemon-sapphire-version-game-boy-advance-lets-fight-it.png",
        source_page="https://www.mobygames.com/game/13770/pokemon-sapphire-version/screenshots/gameboy-advance/60023/",
    ),
    BattleSceneSource(
        game="Pokemon Emerald",
        slug="pokemon_emerald",
        image_url="https://cdn.mobygames.com/screenshots/2366139-pokemon-emerald-version-game-boy-advance-pokemon-battle.png",
        source_page="https://www.mobygames.com/game/19958/pokemon-emerald-version/screenshots/gameboy-advance/109703/",
    ),
    BattleSceneSource(
        game="Pokemon FireRed",
        slug="pokemon_firered",
        image_url="https://cdn.mobygames.com/screenshots/559400-pokemon-firered-version-game-boy-advance-battling.png",
        source_page="https://www.mobygames.com/game/14083/pokemon-firered-version/screenshots/gameboy-advance/267500/",
    ),
    BattleSceneSource(
        game="Pokemon LeafGreen",
        slug="pokemon_leafgreen",
        image_url="https://cdn.mobygames.com/screenshots/559403-pokemon-leafgreen-version-game-boy-advance-your-rival.png",
        source_page="https://www.mobygames.com/game/14084/pokemon-leafgreen-version/screenshots/gameboy-advance/267502/",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download battle-scene images per supported game")
    parser.add_argument("--output-root", type=str, default="assets/battle_scenes")
    parser.add_argument("--manifest-out", type=str, default="")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-per-game", type=int, default=12, help="Max images to keep per game (including base_scene)")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def download_bytes(url: str, timeout_sec: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PokeAchieve trainer bootstrap)"})
    with urllib.request.urlopen(req, timeout=int(timeout_sec)) as resp:
        return resp.read()


def discover_screenshot_urls(source: BattleSceneSource, timeout_sec: int, cap: int) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()

    def _add(url_value: str):
        text = str(url_value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        urls.append(text)

    _add(source.image_url)
    if len(urls) >= int(cap):
        return urls[: int(cap)]

    try:
        html_bytes = download_bytes(source.source_page, timeout_sec=timeout_sec)
        html = html_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return urls[: int(cap)]

    pattern = re.compile(r"https://cdn\.mobygames\.com/screenshots/[A-Za-z0-9._\-/%]+", re.IGNORECASE)
    for match in pattern.findall(html):
        _add(match)
        if len(urls) >= int(cap):
            break
    return urls[: int(cap)]


def sha256_hex(payload: bytes) -> str:
    h = hashlib.sha256()
    h.update(payload)
    return h.hexdigest()


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(args.manifest_out).resolve() if str(args.manifest_out).strip() else (output_root / "manifest.json")

    rows: List[Dict[str, object]] = []
    failures: List[Dict[str, object]] = []

    for source in SCENE_SOURCES:
        game_dir = output_root / source.slug
        game_dir.mkdir(parents=True, exist_ok=True)
        out_path = game_dir / "base_scene.png"

        max_per_game = max(1, min(100, int(args.max_per_game)))
        discovered = discover_screenshot_urls(source, timeout_sec=int(args.timeout), cap=max_per_game)
        game_success = 0

        for idx, image_url in enumerate(discovered):
            name = "base_scene.png" if idx == 0 else f"scene_{idx:03d}.png"
            scene_path = game_dir / name
            if scene_path.exists() and not bool(args.overwrite):
                existing_bytes = scene_path.read_bytes()
                rows.append(
                    {
                        "game": source.game,
                        "slug": source.slug,
                        "status": "skipped_exists",
                        "path": str(scene_path),
                        "bytes": int(len(existing_bytes)),
                        "sha256": sha256_hex(existing_bytes),
                        "image_url": image_url,
                        "source_page": source.source_page,
                    }
                )
                game_success += 1
                continue
            try:
                payload = download_bytes(image_url, timeout_sec=int(args.timeout))
                scene_path.write_bytes(payload)
                rows.append(
                    {
                        "game": source.game,
                        "slug": source.slug,
                        "status": "downloaded",
                        "path": str(scene_path),
                        "bytes": int(len(payload)),
                        "sha256": sha256_hex(payload),
                        "image_url": image_url,
                        "source_page": source.source_page,
                    }
                )
                game_success += 1
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                failure_row = {
                    "game": source.game,
                    "slug": source.slug,
                    "status": "failed",
                    "path": str(scene_path),
                    "image_url": image_url,
                    "source_page": source.source_page,
                    "error": str(exc),
                }
                failures.append(failure_row)
                rows.append(failure_row)

        if game_success <= 0:
            failure_row = {
                "game": source.game,
                "slug": source.slug,
                "status": "failed",
                "path": str(out_path),
                "image_url": source.image_url,
                "source_page": source.source_page,
                "error": "no_scenes_downloaded",
            }
            failures.append(failure_row)
            rows.append(failure_row)

    payload = {
        "output_root": str(output_root),
        "total": int(len(SCENE_SOURCES)),
        "downloaded": int(sum(1 for r in rows if str(r.get("status")) == "downloaded")),
        "skipped_exists": int(sum(1 for r in rows if str(r.get("status")) == "skipped_exists")),
        "failed": int(len(failures)),
        "games": rows,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    if failures:
        sys.exit(2)


if __name__ == "__main__":
    main()

