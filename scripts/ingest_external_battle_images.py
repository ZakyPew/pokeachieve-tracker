#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image


@dataclass(frozen=True)
class GameConfig:
    game: str
    slug: str
    max_species: int
    spriters_game_path: str


GAME_CONFIGS: List[GameConfig] = [
    GameConfig("Pokemon Red", "pokemon_red", 151, "/game_boy_gbc/pokemonredblue/"),
    GameConfig("Pokemon Blue", "pokemon_blue", 151, "/game_boy_gbc/pokemonredblue/"),
    GameConfig("Pokemon Gold", "pokemon_gold", 251, "/game_boy_gbc/pokemongoldsilver/"),
    GameConfig("Pokemon Silver", "pokemon_silver", 251, "/game_boy_gbc/pokemongoldsilver/"),
    GameConfig("Pokemon Crystal", "pokemon_crystal", 251, "/game_boy_gbc/pokemoncrystal/"),
    GameConfig("Pokemon Ruby", "pokemon_ruby", 386, "/game_boy_advance/pokemonrubysapphire/"),
    GameConfig("Pokemon Sapphire", "pokemon_sapphire", 386, "/game_boy_advance/pokemonrubysapphire/"),
    GameConfig("Pokemon Emerald", "pokemon_emerald", 386, "/game_boy_advance/pokemonemerald/"),
    GameConfig("Pokemon FireRed", "pokemon_firered", 151, "/game_boy_advance/pokemonfireredleafgreen/"),
    GameConfig("Pokemon LeafGreen", "pokemon_leafgreen", 151, "/game_boy_advance/pokemonfireredleafgreen/"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest external sprite/battle images into guided-training import queues")
    parser.add_argument("--games", type=str, default="", help="Comma-separated game slugs; default all")
    parser.add_argument("--include-gen1", action="store_true", help="Include Pokemon Red/Blue in default runs")
    parser.add_argument("--per-game-limit", type=int, default=50, help="Target images per game")
    parser.add_argument("--imports-root", type=str, default=str(Path.home() / ".pokeachieve" / "imports"))
    parser.add_argument("--guided-root", type=str, default=str(Path.home() / ".pokeachieve" / "guided_training"))
    parser.add_argument("--sources", type=str, default="serebii,bulbagarden,spriters")
    parser.add_argument(
        "--output-mode",
        type=str,
        default="imports",
        choices=["imports", "guided", "both"],
        help="Where to place downloaded assets",
    )
    parser.add_argument("--add-per-game", type=int, default=0, help="If >0, add this many new images per game regardless of existing counts")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest-out", type=str, default="")
    return parser.parse_args()


def norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def selected_games(raw: str, include_gen1: bool = False) -> List[GameConfig]:
    tokens = [norm_key(p) for p in str(raw or "").split(",") if str(p).strip()]
    if not tokens:
        if bool(include_gen1):
            return list(GAME_CONFIGS)
        return [cfg for cfg in GAME_CONFIGS if cfg.slug not in {"pokemon_red", "pokemon_blue"}]
    wanted = set(tokens)
    out: List[GameConfig] = []
    for cfg in GAME_CONFIGS:
        if norm_key(cfg.slug) in wanted or norm_key(cfg.game) in wanted:
            out.append(cfg)
    return out


def fetch_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (PokeAchieve External Ingest)",
            "Accept": "text/html,application/json,image/png,image/*;q=0.8,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_text(url: str, timeout: int) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", "ignore")


def safe_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def load_species_map_from_tracker(repo_root: Path) -> Dict[int, str]:
    tracker_path = repo_root / "tracker_gui.py"
    text = tracker_path.read_text(encoding="utf-8", errors="ignore")
    marker = "POKEMON_NAMES = {"
    start = text.find(marker)
    if start < 0:
        return {}
    end = text.find("\n    }", start)
    if end < 0:
        return {}
    block = text[start:end]
    out: Dict[int, str] = {}
    for sid_txt, name in re.findall(r"(\d+)\s*:\s*\"([^\"]+)\"", block):
        try:
            sid = int(sid_txt)
        except Exception:
            continue
        if sid > 0:
            out[sid] = str(name).strip()
    return out


def verify_image(payload: bytes) -> bool:
    try:
        from io import BytesIO

        with Image.open(BytesIO(payload)) as img:
            img.verify()
        return True
    except Exception:
        return False


def serebii_page_for_game(cfg: GameConfig, sid: int) -> str:
    if cfg.slug in {"pokemon_red", "pokemon_blue"}:
        return f"https://www.serebii.net/pokedex/{int(sid):03d}.shtml"
    if cfg.slug in {"pokemon_gold", "pokemon_silver", "pokemon_crystal"}:
        return f"https://www.serebii.net/pokedex-gs/{int(sid):03d}.shtml"
    return f"https://www.serebii.net/pokedex-rs/{int(sid):03d}.shtml"


def serebii_priority_tokens(cfg: GameConfig, sid: int) -> List[str]:
    id_token = f"/{int(sid):03d}.png"
    if cfg.slug == "pokemon_red":
        return [f"/pokearth/sprites/rb{id_token}", f"/pokearth/sprites/green{id_token}", f"/pokearth/sprites/yellow{id_token}"]
    if cfg.slug == "pokemon_blue":
        return [f"/pokearth/sprites/rb{id_token}", f"/pokearth/sprites/yellow{id_token}", f"/pokearth/sprites/green{id_token}"]
    if cfg.slug == "pokemon_gold":
        return [f"/pokearth/sprites/gold{id_token}"]
    if cfg.slug == "pokemon_silver":
        return [f"/pokearth/sprites/silver{id_token}"]
    if cfg.slug == "pokemon_crystal":
        return [f"/pokearth/sprites/crystal{id_token}"]
    if cfg.slug == "pokemon_ruby":
        return [f"/pokearth/sprites/ruby{id_token}", f"/pokearth/sprites/rs{id_token}"]
    if cfg.slug == "pokemon_sapphire":
        return [f"/pokearth/sprites/sapphire{id_token}", f"/pokearth/sprites/rs{id_token}"]
    if cfg.slug == "pokemon_emerald":
        return [f"/pokearth/sprites/emerald{id_token}"]
    if cfg.slug in {"pokemon_firered", "pokemon_leafgreen"}:
        return [f"/pokearth/sprites/frlg{id_token}"]
    return ["/pokearth/sprites/"]


def ingest_from_serebii(cfg: GameConfig, sid: int, timeout: int, page_cache: Dict[str, str]) -> Optional[Tuple[bytes, str]]:
    page_url = serebii_page_for_game(cfg, sid)
    html = page_cache.get(page_url)
    if html is None:
        html = fetch_text(page_url, timeout=timeout)
        page_cache[page_url] = html
    srcs = re.findall(r"src=[\"']([^\"']+\.(?:png|gif|jpg|jpeg))[\"']", html, flags=re.I)
    if not srcs:
        return None
    candidates: List[str] = []
    for token in serebii_priority_tokens(cfg, sid):
        for raw in srcs:
            if token in raw:
                full = raw if raw.startswith("http") else ("https://www.serebii.net" + raw)
                candidates.append(full)
    if not candidates:
        for raw in srcs:
            if "/pokearth/sprites/" in raw and f"/{int(sid):03d}." in raw:
                full = raw if raw.startswith("http") else ("https://www.serebii.net" + raw)
                candidates.append(full)
    for url in candidates:
        try:
            payload = fetch_bytes(url, timeout=timeout)
            if payload and verify_image(payload):
                return payload, url
        except Exception:
            continue
    return None


def bulbagarden_titles_for_game(cfg: GameConfig, sid: int) -> List[str]:
    sid3 = f"{int(sid):03d}"
    if cfg.slug in {"pokemon_red", "pokemon_blue"}:
        return [f"Spr_1b_{sid3}.png"]
    if cfg.slug == "pokemon_gold":
        return [f"Spr_2g_{sid3}.png"]
    if cfg.slug == "pokemon_silver":
        return [f"Spr_2s_{sid3}.png"]
    if cfg.slug == "pokemon_crystal":
        return [f"Spr_2c_{sid3}.png"]
    if cfg.slug in {"pokemon_ruby", "pokemon_sapphire"}:
        return [f"Spr_3r_{sid3}.png"]
    if cfg.slug == "pokemon_emerald":
        return [f"Spr_3e_{sid3}.png"]
    if cfg.slug == "pokemon_firered":
        return [f"Spr_3f_{sid3}.png"]
    if cfg.slug == "pokemon_leafgreen":
        return [f"Spr_3l_{sid3}.png"]
    return []


def ingest_from_bulbagarden(cfg: GameConfig, sid: int, timeout: int) -> Optional[Tuple[bytes, str]]:
    base = "https://archives.bulbagarden.net/w/api.php"
    for title in bulbagarden_titles_for_game(cfg, sid):
        params = {
            "action": "query",
            "titles": f"File:{title}",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        try:
            raw = fetch_bytes(url, timeout=timeout)
            parsed = json.loads(raw.decode("utf-8", "ignore"))
            pages = parsed.get("query", {}).get("pages", {})
            image_url = ""
            if isinstance(pages, dict):
                for _, page in pages.items():
                    infos = page.get("imageinfo", []) if isinstance(page, dict) else []
                    if isinstance(infos, list) and infos:
                        image_url = str(infos[0].get("url") or "").strip()
                        if image_url:
                            break
            if not image_url:
                continue
            payload = fetch_bytes(image_url, timeout=timeout)
            if payload and verify_image(payload):
                return payload, image_url
        except Exception:
            continue
    return None


def ingest_from_spriters(cfg: GameConfig, sid: int, species_name: str, timeout: int, browse_cache: Dict[str, str], asset_cache: Dict[str, str]) -> Optional[Tuple[bytes, str]]:
    query = f"g:{species_name} {cfg.game}"
    browse_url = "https://www.spriters-resource.com/browse/?name=" + urllib.parse.quote(query)
    html = browse_cache.get(browse_url)
    if html is None:
        html = fetch_text(browse_url, timeout=timeout)
        browse_cache[browse_url] = html

    links = re.findall(r"href=[\"']([^\"']+/asset/\d+/)[\"']", html, flags=re.I)
    filtered = []
    for link in links:
        if cfg.spriters_game_path in link:
            filtered.append(link)
    seen: set[str] = set()
    deduped: List[str] = []
    for link in filtered:
        full = link if link.startswith("http") else ("https://www.spriters-resource.com" + link)
        if full in seen:
            continue
        seen.add(full)
        deduped.append(full)
    for page_url in deduped[:3]:
        page_html = asset_cache.get(page_url)
        if page_html is None:
            try:
                page_html = fetch_text(page_url, timeout=timeout)
            except Exception:
                continue
            asset_cache[page_url] = page_html
        m = re.search(r"id=[\"']download[\"'][^>]*href=[\"']([^\"']+)[\"']", page_html, flags=re.I)
        if not m:
            m = re.search(r"href=[\"']([^\"']+/media/assets/[^\"']+\.(?:png|gif|jpg|jpeg)(?:\?[^\"']*)?)[\"']", page_html, flags=re.I)
            if not m:
                continue
        raw_url = str(m.group(1)).strip()
        img_url = raw_url if raw_url.startswith("http") else ("https://www.spriters-resource.com" + raw_url)
        try:
            payload = fetch_bytes(img_url, timeout=timeout)
            if payload and verify_image(payload):
                return payload, img_url
        except Exception:
            continue
    return None


def save_import_image(out_dir: Path, source: str, sid: int, species_name: str, payload: bytes, overwrite: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"webseed_ext_{source}_{int(sid):03d}_{safe_name(species_name) or 'species'}"
    target = out_dir / f"{stem}.png"
    if target.exists() and not overwrite:
        idx = 1
        while True:
            candidate = out_dir / f"{stem}_{idx:03d}.png"
            if not candidate.exists():
                target = candidate
                break
            idx += 1
    target.write_bytes(payload)
    return target


def save_guided_sample(guided_root: Path, game_slug: str, source: str, sid: int, species_name: str, payload: bytes, source_url: str, overwrite: bool) -> Path:
    label = f"{int(sid):03d}_{safe_name(species_name) or f'species_{int(sid):03d}'}"
    out_dir = guided_root / game_slug / label
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"trusted_ext_{source}_{int(sid):03d}_{safe_name(species_name) or 'species'}"
    target = out_dir / f"{stem}.png"
    if target.exists() and not overwrite:
        idx = 1
        while True:
            candidate = out_dir / f"{stem}_{idx:03d}.png"
            if not candidate.exists():
                target = candidate
                break
            idx += 1
    target.write_bytes(payload)
    meta = {
        "species_id": int(sid),
        "species_name": str(species_name),
        "source": str(source),
        "source_url": str(source_url),
        "trusted_source": True,
    }
    target.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return target


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    species_map = load_species_map_from_tracker(repo_root)
    if not species_map:
        raise RuntimeError("Could not load species name map from tracker_gui.py")

    configs = selected_games(args.games, include_gen1=bool(args.include_gen1))
    if not configs:
        raise RuntimeError("No games selected")

    enabled_sources = [s.strip().lower() for s in str(args.sources or "").split(",") if s.strip()]
    imports_root = Path(args.imports_root).expanduser().resolve()
    guided_root = Path(args.guided_root).expanduser().resolve()
    imports_root.mkdir(parents=True, exist_ok=True)
    guided_root.mkdir(parents=True, exist_ok=True)

    page_cache: Dict[str, str] = {}
    browse_cache: Dict[str, str] = {}
    asset_cache: Dict[str, str] = {}
    rows: List[Dict[str, object]] = []
    summary: Dict[str, Dict[str, int]] = {}

    for cfg in configs:
        out_dir = imports_root / cfg.slug / "unlabeled"
        if str(args.output_mode) == "guided":
            game_guided = guided_root / cfg.slug
            existing_count = len(list(game_guided.rglob("*.png"))) if game_guided.exists() else 0
        elif str(args.output_mode) == "both":
            game_guided = guided_root / cfg.slug
            imports_count = len(list(out_dir.glob("*.png"))) if out_dir.exists() else 0
            guided_count = len(list(game_guided.rglob("*.png"))) if game_guided.exists() else 0
            existing_count = int(max(imports_count, guided_count))
        else:
            existing = list(out_dir.glob("*.png")) if out_dir.exists() else []
            existing_count = len(existing)
        wanted = max(1, int(args.per_game_limit))
        add_count_mode = int(max(0, int(args.add_per_game)))
        added = 0
        attempted = 0
        source_counts: Dict[str, int] = {s: 0 for s in enabled_sources}

        for sid in range(1, int(cfg.max_species) + 1):
            if add_count_mode > 0:
                if added >= add_count_mode:
                    break
            else:
                if existing_count + added >= wanted:
                    break
            name = str(species_map.get(int(sid), f"Pokemon{int(sid)}")).strip()
            if not name:
                continue
            attempted += 1
            saved = False

            for source in enabled_sources:
                result: Optional[Tuple[bytes, str]] = None
                try:
                    if source == "serebii":
                        result = ingest_from_serebii(cfg, sid, timeout=int(args.timeout), page_cache=page_cache)
                    elif source == "bulbagarden":
                        result = ingest_from_bulbagarden(cfg, sid, timeout=int(args.timeout))
                    elif source == "spriters":
                        result = ingest_from_spriters(
                            cfg,
                            sid,
                            name,
                            timeout=int(args.timeout),
                            browse_cache=browse_cache,
                            asset_cache=asset_cache,
                        )
                except Exception as exc:
                    rows.append(
                        {
                            "game": cfg.slug,
                            "species_id": int(sid),
                            "species_name": name,
                            "source": source,
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                    continue

                if result is None:
                    continue
                payload, src_url = result
                saved_paths: List[str] = []
                if str(args.output_mode) in {"imports", "both"}:
                    saved_paths.append(str(save_import_image(out_dir, source, sid, name, payload, overwrite=bool(args.overwrite))))
                if str(args.output_mode) in {"guided", "both"}:
                    saved_paths.append(
                        str(
                            save_guided_sample(
                                guided_root=guided_root,
                                game_slug=cfg.slug,
                                source=source,
                                sid=int(sid),
                                species_name=name,
                                payload=payload,
                                source_url=src_url,
                                overwrite=bool(args.overwrite),
                            )
                        )
                    )
                source_counts[source] = int(source_counts.get(source, 0)) + 1
                added += 1
                saved = True
                rows.append(
                    {
                        "game": cfg.slug,
                        "species_id": int(sid),
                        "species_name": name,
                        "source": source,
                        "status": "saved",
                        "paths": saved_paths,
                        "source_url": src_url,
                        "bytes": int(len(payload)),
                    }
                )
                break

            if not saved:
                rows.append(
                    {
                        "game": cfg.slug,
                        "species_id": int(sid),
                        "species_name": name,
                        "status": "not_found",
                    }
                )

        summary[cfg.slug] = {
            "mode": str(args.output_mode),
            "requested_total": int(wanted),
            "add_per_game": int(add_count_mode),
            "existing_before": int(existing_count),
            "added": int(added),
            "attempted_species": int(attempted),
            "saved_total": int(existing_count + added),
            "saved_serebii": int(source_counts.get("serebii", 0)),
            "saved_bulbagarden": int(source_counts.get("bulbagarden", 0)),
            "saved_spriters": int(source_counts.get("spriters", 0)),
        }

    payload = {
        "imports_root": str(imports_root),
        "sources": list(enabled_sources),
        "summary": summary,
        "rows": rows,
    }
    if str(args.manifest_out or "").strip():
        out_path = Path(str(args.manifest_out)).expanduser().resolve()
    else:
        out_path = imports_root / "external_ingest_manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(out_path), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
