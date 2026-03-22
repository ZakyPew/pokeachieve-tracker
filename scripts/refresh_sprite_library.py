#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple


PREFIX_URLS: Dict[str, List[str]] = {
    "generation_i_red_blue": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-i/red-blue/{sid}.png",
    ],
    "generation_ii_gold": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-ii/gold/{sid}.png",
    ],
    "generation_ii_silver": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-ii/silver/{sid}.png",
    ],
    "generation_iii_ruby_sapphire": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/ruby-sapphire/{sid}.png",
    ],
    "generation_iii_emerald": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/emerald/{sid}.png",
    ],
    "generation_iii_firered_leafgreen": [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/firered-leafgreen/{sid}.png",
    ],
}


MAX_SPECIES_BY_PREFIX: Dict[str, int] = {
    "generation_i_red_blue": 151,
    "generation_ii_gold": 251,
    "generation_ii_silver": 251,
    "generation_iii_ruby_sapphire": 386,
    "generation_iii_emerald": 386,
    # FRLG has dedicated front sprites for a limited subset in this source.
    "generation_iii_firered_leafgreen": 188,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh local per-game sprite library automatically")
    parser.add_argument("--sprites-dir", type=str, default=str(Path.home() / ".pokeachieve" / "sprites"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest-out", type=str, default="")
    return parser.parse_args()


def fetch_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PokeAchieve Sprite Refresher)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def try_download(prefix: str, sid: int, timeout: int) -> Tuple[bytes | None, str]:
    for template in PREFIX_URLS.get(prefix, []):
        url = template.format(sid=int(sid))
        try:
            payload = fetch_bytes(url, timeout=timeout)
            if payload:
                return payload, url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None, ""


def main() -> None:
    args = parse_args()
    sprites_dir = Path(args.sprites_dir).expanduser().resolve()
    sprites_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    summary: Dict[str, Dict[str, int]] = {}

    for prefix, max_species in MAX_SPECIES_BY_PREFIX.items():
        downloaded = 0
        skipped = 0
        missing = 0
        for sid in range(1, int(max_species) + 1):
            out_path = sprites_dir / f"{prefix}_{sid}.png"
            if out_path.exists() and not bool(args.overwrite):
                skipped += 1
                continue
            payload, used_url = try_download(prefix, sid, timeout=int(args.timeout))
            if payload is None:
                missing += 1
                rows.append(
                    {
                        "prefix": prefix,
                        "species_id": int(sid),
                        "status": "missing",
                        "path": str(out_path),
                    }
                )
                continue
            out_path.write_bytes(payload)
            downloaded += 1
            rows.append(
                {
                    "prefix": prefix,
                    "species_id": int(sid),
                    "status": "downloaded",
                    "path": str(out_path),
                    "source_url": used_url,
                    "bytes": int(len(payload)),
                }
            )
        summary[prefix] = {
            "downloaded": int(downloaded),
            "skipped_exists": int(skipped),
            "missing": int(missing),
            "expected": int(max_species),
        }

    payload = {
        "sprites_dir": str(sprites_dir),
        "summary": summary,
        "rows": rows,
    }

    manifest_out_raw = str(args.manifest_out or "").strip()
    manifest_path = Path(manifest_out_raw).expanduser().resolve() if manifest_out_raw else (sprites_dir / "refresh_manifest.json")
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"sprites_dir": str(sprites_dir), "summary": summary, "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
