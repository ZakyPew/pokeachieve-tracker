import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def _load_manifest_frames(path: Path) -> List[Path]:
    rows: List[Path] = []
    with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            raw_image = str(payload.get("image") or payload.get("frame") or payload.get("path") or "").strip()
            if not raw_image:
                continue
            image_path = Path(raw_image)
            if not image_path.is_absolute():
                image_path = (path.parent / image_path).resolve()
            if image_path.exists():
                rows.append(image_path)
    rows.sort(key=_natural_sort_key)
    return rows


def _discover_frames(frames_dir: Path, globs: List[str]) -> List[Path]:
    found: List[Path] = []
    seen = set()
    for pattern in globs:
        for path in frames_dir.glob(pattern):
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(path.resolve())
    found.sort(key=_natural_sort_key)
    return found


def _load_species_lookup() -> Dict[int, str]:
    table = getattr(getattr(tracker_mod, "PokemonMemoryReader", object), "POKEMON_NAMES", {})
    out: Dict[int, str] = {}
    if isinstance(table, dict) and table:
        for raw_id, raw_name in table.items():
            try:
                sid = int(raw_id)
            except Exception:
                continue
            name = str(raw_name or "").strip()
            if sid > 0 and name:
                out[int(sid)] = str(name)
        if out:
            return out

    # Fallback parser if import-time symbols change.
    tracker_path = REPO_ROOT / "tracker_gui.py"
    text = tracker_path.read_text(encoding="utf-8", errors="ignore")
    marker = "POKEMON_NAMES = {"
    start = text.find(marker)
    if start < 0:
        return out
    end = text.find("\n    }", start)
    if end < 0:
        return out
    block = text[start:end]
    for sid_txt, name in re.findall(r"(\d+)\s*:\s*\"([^\"]+)\"", block):
        try:
            sid = int(sid_txt)
        except Exception:
            continue
        if sid > 0:
            out[int(sid)] = str(name).strip()
    return out


def _build_config(args, candidate_ids: List[int]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "video_encounter_enabled": True,
        "video_encounter_detection_mode": str(args.detection_mode),
        "video_track_all_games": True,
        "video_allow_unknown_species": True,
        "active_game_name": str(args.game),
        "selected_game": str(args.game),
        "video_obs_source_name": str(args.source_name),
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

    if not args.keep_scene_profiles:
        config["video_obs_source_name"] = str(args.source_name)
        config["video_obs_scene_profiles"] = [
            {
                "name": "Replay Scene",
                "source_name": str(args.source_name),
                "enabled": True,
                "ocr_roi": str(args.ocr_roi),
                "sprite_roi": str(args.sprite_roi),
                "shiny_roi": str(args.shiny_roi),
                "nameplate_roi": str(args.nameplate_roi),
            }
        ]

    if candidate_ids:
        config["video_candidate_species_ids"] = [int(sid) for sid in candidate_ids if int(sid) > 0]
    if int(args.target_id) > 0:
        config["video_target_species_id"] = int(args.target_id)

    return config


def _pick(encounter: Optional[Dict[str, Any]], meta: Dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(encounter, dict) and key in encounter:
        return encounter.get(key, default)
    return meta.get(key, default)


class ReplayVideoEncounterReader(tracker_mod.OBSVideoEncounterReader):
    def __init__(self, frames: List[Path], config: Dict[str, Any], species_lookup: Dict[int, str]):
        super().__init__(config=config, species_lookup=species_lookup)
        self._replay_frames = list(frames)
        self._replay_index = 0
        self._replay_last_frame: Optional[Path] = None

    @property
    def replay_index(self) -> int:
        return int(self._replay_index)

    @property
    def replay_last_frame(self) -> Optional[Path]:
        return self._replay_last_frame

    def is_ready(self) -> bool:
        if not self.is_enabled():
            self._set_meta("disabled")
            return False
        if not getattr(tracker_mod, "PIL_AVAILABLE", False):
            self._set_meta(
                "pil_unavailable",
                detail=str(getattr(tracker_mod, "PIL_IMPORT_ERROR", "Pillow import failed") or "Pillow import failed"),
                install_hint="pip install pillow",
            )
            return False
        if not self._scene_profiles():
            self._set_meta("obs_source_missing")
            return False
        return True

    def _capture_frame_payload(self, source_override: Optional[str] = None):
        if self._replay_index >= len(self._replay_frames):
            self._set_meta(
                "replay_exhausted",
                frame_index=int(self._replay_index),
                frame_count=int(len(self._replay_frames)),
            )
            return None

        frame_path = self._replay_frames[self._replay_index]
        frame_index = int(self._replay_index)
        self._replay_index += 1
        self._replay_last_frame = frame_path

        try:
            image = tracker_mod.Image.open(str(frame_path))
            image.load()
            image = image.convert("RGB")
        except Exception as exc:
            self._set_meta(
                "replay_frame_load_failed",
                frame=str(frame_path),
                frame_index=int(frame_index),
                error=str(exc),
            )
            return None

        source_name = str(source_override or self._cfg_str("video_obs_source_name", "ReplaySource")).strip() or "ReplaySource"
        return {
            "image": image,
            "png_blob": b"",
            "source": source_name,
            "width": int(image.width),
            "height": int(image.height),
            "frame_path": str(frame_path),
            "frame_index": int(frame_index),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline targeted replay harness for OBSVideoEncounterReader sprite decisions.")
    parser.add_argument("--game", type=str, default="Pokemon Emerald")
    parser.add_argument("--source-name", type=str, default="ReplaySource")
    parser.add_argument("--detection-mode", type=str, choices=["sprite", "text"], default="sprite")
    parser.add_argument("--frames-dir", type=Path, default=None, help="Directory containing sequential replay frames.")
    parser.add_argument("--manifest", type=Path, default=None, help="JSONL manifest with frame paths (uses `image` field).")
    parser.add_argument("--glob", action="append", default=[], help="Glob pattern(s) under --frames-dir (can repeat).")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means all frames after start-index.")
    parser.add_argument("--frame-delay-ms", type=float, default=0.0, help="Optional sleep between frames.")
    parser.add_argument("--candidate-ids", type=str, default="", help="Comma-separated species IDs for route candidate pool.")
    parser.add_argument("--target-id", type=int, default=0)
    parser.add_argument("--config-json", type=Path, default=None, help="Optional JSON config to merge before replay.")
    parser.add_argument("--keep-scene-profiles", action="store_true", help="Do not override scene profiles from --config-json.")
    parser.add_argument("--sprite-roi", type=str, default="0.56,0.14,0.92,0.62")
    parser.add_argument("--ocr-roi", type=str, default="0.05,0.70,0.95,0.96")
    parser.add_argument("--nameplate-roi", type=str, default="0.02,0.04,0.48,0.24")
    parser.add_argument("--shiny-roi", type=str, default="0.58,0.16,0.92,0.52")
    parser.add_argument("--output-jsonl", type=Path, default=None, help="Write per-frame trace JSONL.")
    parser.add_argument("--quiet", action="store_true", help="Print only summary.")
    args = parser.parse_args()

    if args.manifest is None and args.frames_dir is None:
        raise SystemExit("Provide either --manifest or --frames-dir.")

    if args.manifest is not None:
        frame_paths = _load_manifest_frames(args.manifest.resolve())
    else:
        frame_globs = list(args.glob or [])
        if not frame_globs:
            frame_globs = ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp"]
        frame_paths = _discover_frames(args.frames_dir.resolve(), frame_globs)

    if not frame_paths:
        raise SystemExit("No replay frames found.")

    start_index = max(0, int(args.start_index))
    if start_index >= len(frame_paths):
        raise SystemExit(f"start-index {start_index} is out of range for {len(frame_paths)} frame(s).")

    frame_paths = frame_paths[start_index:]
    if int(args.max_frames) > 0:
        frame_paths = frame_paths[: int(args.max_frames)]

    candidate_ids = _parse_candidate_ids(args.candidate_ids)
    species_lookup = _load_species_lookup()
    config = _build_config(args, candidate_ids)
    reader = ReplayVideoEncounterReader(frame_paths, config=config, species_lookup=species_lookup)

    if not reader.is_ready():
        print(json.dumps({"ready": False, "meta": reader.get_last_meta()}, ensure_ascii=True))
        return 2

    reason_counter: Counter = Counter()
    conflict_counter: Counter = Counter()
    started_frame_by_token: Dict[int, int] = {}
    resolve_latencies: List[int] = []
    resolved_counter = 0
    unresolved_with_best_counter = 0
    abra_miss_counter = 0

    out_handle = None
    if args.output_jsonl:
        args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        out_handle = args.output_jsonl.open("w", encoding="utf-8")

    for replay_i in range(len(frame_paths)):
        encounter = reader.read_wild_encounter(str(args.game))
        meta = reader.get_last_meta()
        frame_path = reader.replay_last_frame or frame_paths[min(replay_i, len(frame_paths) - 1)]

        reason = str(meta.get("reason") or "")
        reason_counter[reason] += 1

        species_id = int(_pick(encounter, meta, "species_id", 0) or 0)
        phase = str(_pick(encounter, meta, "encounter_phase", ""))
        token = int(_pick(encounter, meta, "encounter_token", 0) or 0)
        best_sid = int(_pick(encounter, meta, "sprite_best_species_id", 0) or 0)
        robust_sid = int(_pick(encounter, meta, "sprite_robust_best_species_id", 0) or 0)
        posterior_sid = int(_pick(encounter, meta, "sprite_posterior_top_species_id", 0) or 0)
        posterior_prob = float(_pick(encounter, meta, "sprite_posterior_top_probability", 0.0) or 0.0)
        margin = int(_pick(encounter, meta, "sprite_distance_margin", 0) or 0)
        dist = int(_pick(encounter, meta, "sprite_match_distance", 999) or 999)
        score = int(_pick(encounter, meta, "sprite_score", 0) or 0)
        fg_present = bool(_pick(encounter, meta, "sprite_foreground_present", False))
        lock_count = int(_pick(encounter, meta, "species_lock_count", 0) or 0)
        lock_required = int(_pick(encounter, meta, "species_lock_required", 0) or 0)

        if token > 0 and token not in started_frame_by_token:
            started_frame_by_token[token] = int(replay_i)
        if species_id > 0:
            resolved_counter += 1
            if token > 0 and token in started_frame_by_token:
                resolve_latencies.append(int(replay_i - started_frame_by_token[token]))

        if best_sid > 0 and posterior_sid > 0 and best_sid != posterior_sid:
            conflict_counter["best_vs_posterior"] += 1
        if best_sid > 0 and robust_sid > 0 and best_sid != robust_sid:
            conflict_counter["best_vs_robust"] += 1
        if species_id > 0 and best_sid > 0 and species_id != best_sid:
            conflict_counter["resolved_not_best"] += 1
        if reason in {"sprite_species_not_resolved", "pending_confirmations"} and best_sid > 0:
            unresolved_with_best_counter += 1
            conflict_counter["unresolved_with_best"] += 1
        if best_sid == 63 and species_id != 63:
            abra_miss_counter += 1
            conflict_counter["abra_best_not_resolved_as_abra"] += 1

        if not args.quiet:
            print(
                f"[{replay_i:04d}] {frame_path.name} "
                f"reason={reason or '-'} phase={phase or '-'} token={token} sid={species_id} "
                f"best={best_sid} robust={robust_sid} post={posterior_sid} post_p={posterior_prob:.3f} "
                f"dist={dist} margin={margin} score={score} fg={int(fg_present)} lock={lock_count}/{lock_required}"
            )

        if out_handle is not None:
            row = {
                "frame_index": int(replay_i),
                "frame_path": str(frame_path),
                "reason": str(reason),
                "encounter": dict(encounter or {}),
                "meta": dict(meta or {}),
                "phase": str(phase),
                "token": int(token),
                "species_id": int(species_id),
                "sprite_best_species_id": int(best_sid),
                "sprite_robust_best_species_id": int(robust_sid),
                "sprite_posterior_top_species_id": int(posterior_sid),
                "sprite_posterior_top_probability": float(posterior_prob),
                "sprite_match_distance": int(dist),
                "sprite_distance_margin": int(margin),
                "sprite_score": int(score),
                "sprite_foreground_present": bool(fg_present),
                "species_lock_count": int(lock_count),
                "species_lock_required": int(lock_required),
            }
            out_handle.write(json.dumps(row, ensure_ascii=True) + "\n")

        if float(args.frame_delay_ms) > 0:
            time.sleep(max(0.0, float(args.frame_delay_ms) / 1000.0))

    if out_handle is not None:
        out_handle.close()

    latency_ms = [int(v * max(1.0, float(args.frame_delay_ms))) for v in resolve_latencies]
    summary = {
        "frames_processed": int(len(frame_paths)),
        "resolved_events": int(resolved_counter),
        "reasons_top": dict(reason_counter.most_common(10)),
        "conflicts": dict(conflict_counter),
        "unresolved_with_best_count": int(unresolved_with_best_counter),
        "abra_best_not_resolved_as_abra": int(abra_miss_counter),
        "resolve_latency_frames": {
            "count": int(len(resolve_latencies)),
            "min": int(min(resolve_latencies)) if resolve_latencies else None,
            "median": int(sorted(resolve_latencies)[len(resolve_latencies) // 2]) if resolve_latencies else None,
            "max": int(max(resolve_latencies)) if resolve_latencies else None,
        },
        "resolve_latency_ms_estimate": {
            "frame_delay_ms": float(args.frame_delay_ms),
            "count": int(len(latency_ms)),
            "min": int(min(latency_ms)) if latency_ms else None,
            "median": int(sorted(latency_ms)[len(latency_ms) // 2]) if latency_ms else None,
            "max": int(max(latency_ms)) if latency_ms else None,
        },
    }
    print("\nSummary:")
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
