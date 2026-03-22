import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tracker_gui as tracker_mod  # noqa: E402


def _natural_sort_key(path: Path):
    text = str(path.name).lower()
    return [int(chunk) if chunk.isdigit() else chunk for chunk in re.split(r"(\d+)", text)]


def _parse_candidate_ids(raw: str) -> List[int]:
    out: List[int] = []
    seen = set()
    for chunk in str(raw or "").split(","):
        token = str(chunk or "").strip()
        if not token:
            continue
        try:
            sid = int(token)
        except Exception:
            continue
        if sid <= 0 or sid in seen:
            continue
        seen.add(sid)
        out.append(int(sid))
    return out


def _species_lookup() -> Dict[int, str]:
    table = getattr(getattr(tracker_mod, "PokemonMemoryReader", object), "POKEMON_NAMES", {})
    out: Dict[int, str] = {}
    if isinstance(table, dict):
        for raw_id, raw_name in table.items():
            try:
                sid = int(raw_id)
            except Exception:
                continue
            name = str(raw_name or "").strip()
            if sid > 0 and name:
                out[int(sid)] = str(name)
    return out


def _parse_species_id_from_folder_name(name: str) -> int:
    text = str(name or "").strip().lower()
    if not text:
        return 0
    if "__background__" in text or "background" in text:
        return 0
    match = re.match(r"^(\d+)", text)
    if not match:
        return -1
    try:
        sid = int(match.group(1))
    except Exception:
        return -1
    return int(sid) if sid > 0 else -1


def _infer_true_species_id(image_path: Path, game_dir: Path) -> int:
    cur = image_path.parent
    game_dir_resolved = game_dir.resolve()
    while True:
        sid = _parse_species_id_from_folder_name(cur.name)
        if sid >= 0:
            return int(sid)
        if cur.resolve() == game_dir_resolved:
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return -1


def _pick(encounter: Optional[Dict[str, Any]], meta: Dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(encounter, dict) and key in encounter:
        return encounter.get(key, default)
    return meta.get(key, default)


class RepeatFrameReader(tracker_mod.OBSVideoEncounterReader):
    def __init__(
        self,
        frame_path: Path,
        repeat_frames: int,
        config: Dict[str, Any],
        species_lookup: Dict[int, str],
    ):
        super().__init__(config=config, species_lookup=species_lookup)
        self._frame_path = Path(frame_path)
        self._repeat_frames = max(1, int(repeat_frames))
        self._index = 0

    def is_ready(self) -> bool:
        if not self.is_enabled():
            self._set_meta("disabled")
            return False
        if not getattr(tracker_mod, "PIL_AVAILABLE", False):
            self._set_meta("pil_unavailable")
            return False
        return bool(self._frame_path.exists())

    def _capture_frame_payload(self, source_override: Optional[str] = None):
        if int(self._index) >= int(self._repeat_frames):
            self._set_meta(
                "replay_exhausted",
                frame_index=int(self._index),
                frame_count=int(self._repeat_frames),
            )
            return None
        frame_index = int(self._index)
        self._index += 1
        image = tracker_mod.Image.open(str(self._frame_path)).convert("RGB")
        source_name = str(source_override or self._cfg_str("video_obs_source_name", "ReplaySource") or "ReplaySource")
        return {
            "image": image,
            "png_blob": b"",
            "source": source_name,
            "width": int(image.width),
            "height": int(image.height),
            "frame_path": str(self._frame_path),
            "frame_index": int(frame_index),
        }


def _build_config(args, candidate_ids: List[int]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "video_encounter_enabled": True,
        "video_encounter_detection_mode": str(args.detection_mode),
        "video_track_all_games": True,
        "video_allow_unknown_species": True,
        "active_game_name": str(args.game_name),
        "selected_game": str(args.game_name),
        "video_obs_source_name": str(args.source_name),
        "video_require_battle_context": bool(args.require_battle_context),
        "video_obs_scene_profiles": [
            {
                "name": "Replay Scene",
                "source_name": str(args.source_name),
                "enabled": True,
                "ocr_roi": str(args.ocr_roi),
                "sprite_roi": str(args.sprite_roi),
                "shiny_roi": str(args.shiny_roi),
                "nameplate_roi": str(args.nameplate_roi),
            }
        ],
    }
    if args.config_json:
        loaded = json.loads(args.config_json.read_text(encoding="utf-8-sig", errors="ignore"))
        if isinstance(loaded, dict):
            config.update(loaded)
    if candidate_ids:
        config["video_candidate_species_ids"] = [int(sid) for sid in candidate_ids if int(sid) > 0]
    if int(args.target_id) > 0:
        config["video_target_species_id"] = int(args.target_id)
    return config


def _collect_images(game_dir: Path, include_background: bool, only_true_species: Optional[set] = None) -> List[Tuple[Path, int]]:
    images: List[Tuple[Path, int]] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"):
        for path in game_dir.rglob(ext):
            if not path.is_file():
                continue
            sid = _infer_true_species_id(path, game_dir)
            if sid < 0:
                continue
            if sid == 0 and (not include_background):
                continue
            if isinstance(only_true_species, set) and only_true_species and int(sid) not in only_true_species:
                continue
            images.append((path.resolve(), int(sid)))
    images.sort(key=lambda row: _natural_sort_key(row[0]))
    return images


def _finalize_summary(
    rows: List[Dict[str, Any]],
    reason_counter: Counter,
    unresolved_reason_counter: Counter,
    species_lookup: Dict[int, str],
) -> Dict[str, Any]:
    total = len(rows)
    positives = [r for r in rows if int(r.get("true_species_id", 0)) > 0]
    negatives = [r for r in rows if int(r.get("true_species_id", 0)) == 0]
    resolved = [r for r in rows if int(r.get("pred_species_id", 0)) > 0]
    correct = [r for r in positives if int(r.get("pred_species_id", 0)) == int(r.get("true_species_id", 0))]
    unresolved_positive = [r for r in positives if int(r.get("pred_species_id", 0)) <= 0]
    wrong_positive = [
        r
        for r in positives
        if int(r.get("pred_species_id", 0)) > 0 and int(r.get("pred_species_id", 0)) != int(r.get("true_species_id", 0))
    ]
    false_positive_background = [r for r in negatives if int(r.get("pred_species_id", 0)) > 0]
    resolve_steps = [int(r.get("resolve_frame_index", -1)) for r in resolved if int(r.get("resolve_frame_index", -1)) >= 0]

    confusion = Counter()
    for row in wrong_positive:
        true_sid = int(row.get("true_species_id", 0))
        pred_sid = int(row.get("pred_species_id", 0))
        confusion[(true_sid, pred_sid)] += 1

    top_confusions = []
    for (true_sid, pred_sid), count in confusion.most_common(20):
        top_confusions.append(
            {
                "true_species_id": int(true_sid),
                "true_species": str(species_lookup.get(int(true_sid), f"Pokemon #{int(true_sid)}")),
                "pred_species_id": int(pred_sid),
                "pred_species": str(species_lookup.get(int(pred_sid), f"Pokemon #{int(pred_sid)}")),
                "count": int(count),
            }
        )

    return {
        "images_total": int(total),
        "positives": int(len(positives)),
        "background": int(len(negatives)),
        "resolved_total": int(len(resolved)),
        "resolved_rate": float((len(resolved) / total) if total else 0.0),
        "positive_accuracy": float((len(correct) / len(positives)) if positives else 0.0),
        "positive_resolve_rate": float(((len(positives) - len(unresolved_positive)) / len(positives)) if positives else 0.0),
        "positive_unresolved_rate": float((len(unresolved_positive) / len(positives)) if positives else 0.0),
        "positive_wrong_rate": float((len(wrong_positive) / len(positives)) if positives else 0.0),
        "background_false_positive_rate": float((len(false_positive_background) / len(negatives)) if negatives else 0.0),
        "resolve_frame_index": {
            "count": int(len(resolve_steps)),
            "min": int(min(resolve_steps)) if resolve_steps else None,
            "median": int(sorted(resolve_steps)[len(resolve_steps) // 2]) if resolve_steps else None,
            "max": int(max(resolve_steps)) if resolve_steps else None,
        },
        "reasons_top": dict(reason_counter.most_common(20)),
        "unresolved_reasons_top": dict(unresolved_reason_counter.most_common(20)),
        "top_confusions": top_confusions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch single-image replay evaluation for guided training captures.")
    parser.add_argument("--guided-root", type=Path, default=Path.home() / ".pokeachieve" / "guided_training")
    parser.add_argument("--game-slug", type=str, default="pokemon_emerald")
    parser.add_argument("--game-name", type=str, default="Pokemon Emerald")
    parser.add_argument("--source-name", type=str, default="ReplaySource")
    parser.add_argument("--detection-mode", type=str, choices=["sprite", "text"], default="sprite")
    parser.add_argument("--repeat-frames", type=int, default=4)
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--require-battle-context", action="store_true", default=False)
    parser.add_argument("--candidate-ids", type=str, default="")
    parser.add_argument("--only-true-species", type=str, default="")
    parser.add_argument("--auto-candidate-pool-size", type=int, default=0)
    parser.add_argument("--auto-candidate-seed", type=int, default=1337)
    parser.add_argument("--target-id", type=int, default=0)
    parser.add_argument("--config-json", type=Path, default=None)
    parser.add_argument("--include-background", action="store_true", default=False)
    parser.add_argument("--sprite-roi", type=str, default="0.56,0.14,0.92,0.62")
    parser.add_argument("--ocr-roi", type=str, default="0.05,0.70,0.95,0.96")
    parser.add_argument("--nameplate-roi", type=str, default="0.02,0.04,0.48,0.24")
    parser.add_argument("--shiny-roi", type=str, default="0.58,0.16,0.92,0.52")
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    game_dir = (args.guided_root / str(args.game_slug)).expanduser().resolve()
    if not game_dir.exists():
        raise SystemExit(f"Game guided-training directory not found: {game_dir}")

    only_species_set = set(_parse_candidate_ids(args.only_true_species))
    if only_species_set and bool(args.include_background):
        only_species_set.add(0)
    images = _collect_images(
        game_dir,
        include_background=bool(args.include_background),
        only_true_species=only_species_set if only_species_set else None,
    )
    if int(args.max_images) > 0:
        images = images[: int(args.max_images)]
    if not images:
        raise SystemExit(f"No images found under {game_dir}")

    species_lookup = _species_lookup()
    candidate_ids = _parse_candidate_ids(args.candidate_ids)
    config = _build_config(args, candidate_ids)

    out_handle = None
    if args.output_jsonl:
        args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        out_handle = args.output_jsonl.open("w", encoding="utf-8")

    rows: List[Dict[str, Any]] = []
    reason_counter: Counter = Counter()
    unresolved_reason_counter: Counter = Counter()
    all_true_species_ids = sorted({int(sid) for _, sid in images if int(sid) > 0})
    rng = random.Random(int(args.auto_candidate_seed))
    auto_pool_size = max(0, int(args.auto_candidate_pool_size))

    for index, (image_path, true_sid) in enumerate(images):
        dynamic_config = dict(config)
        dynamic_candidates = list(candidate_ids)
        if int(auto_pool_size) > 0:
            pool_size = max(1, int(auto_pool_size))
            pool: List[int] = []
            if int(true_sid) > 0:
                pool.append(int(true_sid))
            remaining = [int(sid) for sid in all_true_species_ids if int(sid) > 0 and int(sid) != int(true_sid)]
            rng.shuffle(remaining)
            for sid in remaining:
                if len(pool) >= int(pool_size):
                    break
                pool.append(int(sid))
            dynamic_candidates = [int(sid) for sid in pool if int(sid) > 0]
        if dynamic_candidates:
            dynamic_config["video_candidate_species_ids"] = [int(sid) for sid in dynamic_candidates if int(sid) > 0]
        else:
            dynamic_config.pop("video_candidate_species_ids", None)

        reader = RepeatFrameReader(
            frame_path=image_path,
            repeat_frames=int(args.repeat_frames),
            config=dynamic_config,
            species_lookup=species_lookup,
        )
        if not reader.is_ready():
            continue

        pred_sid = 0
        pred_phase = ""
        pred_source = ""
        resolve_frame_index = -1
        last_meta: Dict[str, Any] = {}
        last_reason = ""
        top3_best: List[int] = []
        best_sid_last = 0

        for frame_i in range(max(1, int(args.repeat_frames))):
            encounter = reader.read_wild_encounter(str(args.game_name))
            meta = dict(reader.get_last_meta() or {})
            last_meta = dict(meta)
            reason = str(meta.get("reason") or "")
            last_reason = str(reason)
            reason_counter[reason] += 1

            species_id = int(_pick(encounter, meta, "species_id", 0) or 0)
            phase = str(_pick(encounter, meta, "encounter_phase", ""))
            species_source = str(_pick(encounter, meta, "species_source", ""))
            best_sid = int(_pick(encounter, meta, "sprite_best_species_id", 0) or 0)
            best_sid_last = int(best_sid)
            top3 = _pick(encounter, meta, "sprite_color_rank_top3", []) or []
            if isinstance(top3, list):
                top3_best = []
                for row in top3[:3]:
                    if not isinstance(row, dict):
                        continue
                    try:
                        sid = int(row.get("species_id", 0) or 0)
                    except Exception:
                        sid = 0
                    if sid > 0:
                        top3_best.append(int(sid))

            if species_id > 0 and pred_sid <= 0:
                pred_sid = int(species_id)
                pred_phase = str(phase)
                pred_source = str(species_source)
                resolve_frame_index = int(frame_i)
                break

        if pred_sid <= 0:
            unresolved_reason_counter[str(last_reason)] += 1

        row = {
            "index": int(index),
            "image_path": str(image_path),
            "true_species_id": int(true_sid),
            "pred_species_id": int(pred_sid),
            "pred_species_source": str(pred_source),
            "pred_phase": str(pred_phase),
            "resolve_frame_index": int(resolve_frame_index),
            "last_reason": str(last_reason),
            "last_best_species_id": int(best_sid_last),
            "last_top3_species_ids": [int(v) for v in list(top3_best[:3])],
            "candidate_species_ids": [int(sid) for sid in dynamic_candidates],
            "last_meta": dict(last_meta),
        }
        rows.append(row)
        if out_handle is not None:
            out_handle.write(json.dumps(row, ensure_ascii=True) + "\n")

        if not args.quiet and (index < 30 or index % 100 == 0):
            true_name = species_lookup.get(int(true_sid), "background" if int(true_sid) == 0 else f"Pokemon #{int(true_sid)}")
            pred_name = species_lookup.get(int(pred_sid), "None" if int(pred_sid) == 0 else f"Pokemon #{int(pred_sid)}")
            print(
                f"[{index:05d}] {image_path.name} true={true_name}({true_sid}) "
                f"pred={pred_name}({pred_sid}) frame={resolve_frame_index} reason={last_reason}"
            )

    if out_handle is not None:
        out_handle.close()

    summary = _finalize_summary(rows, reason_counter, unresolved_reason_counter, species_lookup)
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
