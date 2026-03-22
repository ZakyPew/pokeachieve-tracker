#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image, ImageEnhance, ImageFilter


@dataclass(frozen=True)
class GameConfig:
    game: str
    slug: str
    sprite_prefixes: str


GAME_CONFIGS: List[GameConfig] = [
    GameConfig("Pokemon Red", "pokemon_red", "generation_i_red_blue"),
    GameConfig("Pokemon Blue", "pokemon_blue", "generation_i_red_blue"),
    GameConfig("Pokemon Gold", "pokemon_gold", "generation_ii_gold"),
    GameConfig("Pokemon Silver", "pokemon_silver", "generation_ii_silver"),
    GameConfig("Pokemon Crystal", "pokemon_crystal", "generation_ii_gold,generation_ii_silver"),
    GameConfig("Pokemon Ruby", "pokemon_ruby", "generation_iii_ruby_sapphire"),
    GameConfig("Pokemon Sapphire", "pokemon_sapphire", "generation_iii_ruby_sapphire"),
    GameConfig("Pokemon Emerald", "pokemon_emerald", "generation_iii_emerald,emerald"),
    GameConfig("Pokemon FireRed", "pokemon_firered", "generation_iii_firered_leafgreen"),
    GameConfig("Pokemon LeafGreen", "pokemon_leafgreen", "generation_iii_firered_leafgreen"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 4-step guided training pipeline: collect, synthesize, train, evaluate")
    parser.add_argument("--game", type=str, required=True, help="Game name or slug (e.g. 'Pokemon Emerald' or 'pokemon_emerald')")
    parser.add_argument("--python", type=str, default=sys.executable)
    parser.add_argument("--guided-root", type=str, default=str(Path.home() / ".pokeachieve" / "guided_training"))
    parser.add_argument("--scenes-root", type=str, default="assets/battle_scenes")
    parser.add_argument("--work-root", type=str, default="debug/ai_dataset/by_game")
    parser.add_argument("--models-root", type=str, default="models/by_game")
    parser.add_argument("--samples-per-species", type=int, default=60)
    parser.add_argument("--negative-ratio", type=float, default=0.35)
    parser.add_argument("--real-augments-per-image", type=int, default=10)
    parser.add_argument(
        "--real-sample-policy",
        type=str,
        default="all",
        choices=["all", "trusted_and_ingame", "trusted_only"],
        help="Filter guided real samples by source trust policy",
    )
    parser.add_argument("--focus-real-species", action="store_true", help="Only synthesize species already confirmed in guided labels")
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--input-size", type=int, default=64)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--use-all-scenes", action="store_true", help="Use base_scene + scene_###.png for synthetic generation")
    parser.add_argument("--max-scenes", type=int, default=8, help="Max scene images to use when --use-all-scenes is enabled")
    parser.add_argument("--eval-manifest", type=str, default="", help="Optional replay manifest for eval script")
    parser.add_argument("--download-scenes", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def normalize_key(text: str) -> str:
    return "".join(ch for ch in str(text).strip().lower() if ch.isalnum())


def resolve_game_config(raw: str) -> GameConfig:
    key = normalize_key(raw)
    for cfg in GAME_CONFIGS:
        if key in {normalize_key(cfg.game), normalize_key(cfg.slug)}:
            return cfg
    raise ValueError(f"Unsupported game: {raw}")


def run_cmd(cmd: List[str]) -> None:
    print("[CMD]", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def parse_species_id_from_path(path: Path) -> int:
    token = str(path.name or "").strip()
    if not token:
        return 0
    m = re.match(r"^(\d+)", token)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return 0
    return 0


def infer_class_label_from_path(path: Path) -> str:
    sid = int(parse_species_id_from_path(path))
    if sid > 0:
        return str(int(sid))
    text = str(path.name or "").strip().lower()
    if "background" in text or "negative" in text or "no_pokemon" in text or "nopokemon" in text:
        return "__background__"
    return ""


def iter_images(root: Path) -> Iterable[Path]:
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        yield from root.rglob(ext)


def _load_companion_metadata(image_path: Path) -> Dict[str, object]:
    meta_path = image_path.with_suffix(".json")
    if not meta_path.exists():
        return {}
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _is_trusted_sample(image_path: Path) -> bool:
    meta = _load_companion_metadata(image_path)
    if not meta:
        return False

    if bool(meta.get("trusted_source", False)):
        return True

    source = str(meta.get("source") or "").strip().lower()
    if source in {"serebii", "bulbagarden", "spriters", "spriters_resource"}:
        return True
    return False


def _is_trusted_or_ingame_sample(image_path: Path) -> bool:
    meta = _load_companion_metadata(image_path)
    if not meta:
        return False
    if _is_trusted_sample(image_path):
        return True

    mode = str(meta.get("mode") or "").strip().lower()
    source_name = str(meta.get("source_name") or "").strip().lower()
    signature = str(meta.get("encounter_signature") or "").strip().lower()
    if "import review" in mode:
        return False
    if signature.startswith("video:"):
        return True
    if "hunt" in mode and source_name and source_name != "imports_unlabeled":
        return True
    return False


def copy_real_samples(game_slug: str, guided_root: Path, out_real_root: Path, policy: str = "all") -> Dict[int, int]:
    counts: Dict[int, int] = {}
    source_root = guided_root / game_slug
    if not source_root.exists():
        return counts
    out_real_root.mkdir(parents=True, exist_ok=True)
    for image_path in iter_images(source_root):
        policy_name = str(policy)
        if policy_name == "trusted_and_ingame":
            if not _is_trusted_or_ingame_sample(image_path):
                continue
        elif policy_name == "trusted_only":
            if not _is_trusted_sample(image_path):
                continue
        class_label = infer_class_label_from_path(image_path.parent)
        if not class_label:
            class_label = infer_class_label_from_path(image_path)
        if not class_label:
            continue
        target_dir = out_real_root / str(class_label)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / image_path.name
        if target_path.exists():
            target_path = target_dir / f"{image_path.stem}_{random.randint(100000, 999999)}{image_path.suffix.lower()}"
        shutil.copy2(image_path, target_path)
        sid = int(parse_species_id_from_path(Path(class_label)))
        counts[sid] = int(counts.get(sid, 0)) + 1
    return counts


def make_augmented_variant(img: Image.Image, rng: random.Random) -> Image.Image:
    work = img.convert("RGBA")
    work = ImageEnhance.Brightness(work).enhance(rng.uniform(0.80, 1.20))
    work = ImageEnhance.Contrast(work).enhance(rng.uniform(0.80, 1.20))
    if rng.random() < 0.45:
        work = work.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 1.0)))
    if rng.random() < 0.30:
        crop_j = rng.randint(0, 4)
        if work.width > 16 and work.height > 16 and crop_j > 0:
            work = work.crop((crop_j, crop_j, work.width - crop_j, work.height - crop_j)).resize(img.size, Image.Resampling.BILINEAR)
    return work


def merge_datasets(
    synthetic_root: Path,
    real_root: Path,
    output_labeled_root: Path,
    real_augments_per_image: int,
    seed: int,
) -> Tuple[int, int]:
    if output_labeled_root.exists():
        shutil.rmtree(output_labeled_root, ignore_errors=True)
    output_labeled_root.mkdir(parents=True, exist_ok=True)

    syn_count = 0
    for image_path in iter_images(synthetic_root):
        class_label = infer_class_label_from_path(image_path.parent)
        if not class_label:
            continue
        dst_dir = output_labeled_root / str(class_label)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / image_path.name
        if dst.exists():
            dst = dst_dir / f"{image_path.stem}_{random.randint(100000, 999999)}{image_path.suffix.lower()}"
        shutil.copy2(image_path, dst)
        syn_count += 1

    real_count = 0
    rng = random.Random(int(seed))
    if real_root.exists():
        for image_path in iter_images(real_root):
            class_label = infer_class_label_from_path(image_path.parent)
            if not class_label:
                continue
            dst_dir = output_labeled_root / str(class_label)
            dst_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"real_{image_path.stem}"
            dst = dst_dir / f"{base_name}{image_path.suffix.lower()}"
            shutil.copy2(image_path, dst)
            real_count += 1
            try:
                src = Image.open(image_path).convert("RGBA")
            except Exception:
                continue
            for idx in range(int(max(0, real_augments_per_image))):
                aug = make_augmented_variant(src, rng)
                out_path = dst_dir / f"{base_name}_aug_{idx:02d}.png"
                aug.save(out_path)
                real_count += 1

    return syn_count, real_count


def main() -> None:
    args = parse_args()
    cfg = resolve_game_config(args.game)

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"

    guided_root = Path(args.guided_root).expanduser().resolve()
    scenes_root = Path(args.scenes_root).resolve()
    work_root = Path(args.work_root).resolve()
    models_root = Path(args.models_root).resolve()

    game_work = work_root / cfg.slug
    real_root = game_work / "real_labeled"
    synth_root = game_work / "synthetic_labeled"
    mixed_root = game_work / "labeled"
    clean_preview = game_work / "base_clean.png"

    model_root = models_root / cfg.slug
    model_root.mkdir(parents=True, exist_ok=True)
    onnx_path = model_root / "tracker_species.onnx"
    labels_path = model_root / "tracker_species_labels.json"
    ckpt_path = model_root / "tracker_species.pt"

    if args.overwrite and game_work.exists():
        shutil.rmtree(game_work, ignore_errors=True)
    game_work.mkdir(parents=True, exist_ok=True)

    if args.download_scenes:
        run_cmd([str(args.python), str(scripts_dir / "download_battle_scenes.py"), "--output-root", str(scenes_root)])

    scene_dir = scenes_root / cfg.slug
    base_scene = scene_dir / "base_scene.png"
    if not base_scene.exists():
        raise FileNotFoundError(f"Missing base scene: {base_scene}")

    scene_paths: List[Path] = [base_scene]
    if bool(args.use_all_scenes):
        extra = sorted(scene_dir.glob("scene_*.png"))
        for p in extra:
            if p.is_file():
                scene_paths.append(p)
        # De-duplicate while preserving order.
        _seen_scene: set[str] = set()
        deduped_scene_paths: List[Path] = []
        for p in scene_paths:
            key = str(p.resolve())
            if key in _seen_scene:
                continue
            _seen_scene.add(key)
            deduped_scene_paths.append(p)
        scene_paths = deduped_scene_paths[: max(1, int(args.max_scenes))]

    real_counts = copy_real_samples(cfg.slug, guided_root, real_root, policy=str(args.real_sample_policy))
    species_ids = sorted(int(k) for k in real_counts.keys() if int(k) > 0)
    species_ids_arg = ""
    if bool(args.focus_real_species) and len(species_ids) >= 2:
        species_ids_arg = ",".join(str(sid) for sid in species_ids)

    samples_per_scene = max(1, int(round(float(args.samples_per_species) / float(max(1, len(scene_paths))))))
    for i, scene_path in enumerate(scene_paths):
        synth_cmd = [
            str(args.python),
            str(scripts_dir / "generate_synthetic_emerald_dataset.py"),
            "--base-image",
            str(scene_path),
            "--output-dir",
            str(synth_root),
            "--sprite-prefixes",
            str(cfg.sprite_prefixes),
            "--samples-per-species",
            str(int(samples_per_scene)),
            "--negative-ratio",
            str(float(args.negative_ratio)),
            "--seed",
            str(int(args.seed) + i),
        ]
        if i == 0:
            synth_cmd.extend(["--save-base-clean", str(clean_preview)])
        else:
            synth_cmd.append("--append-manifest")
        if species_ids_arg:
            synth_cmd.extend(["--species-ids", species_ids_arg])
        run_cmd(synth_cmd)

    syn_count, real_count = merge_datasets(
        synthetic_root=synth_root,
        real_root=real_root,
        output_labeled_root=mixed_root,
        real_augments_per_image=int(args.real_augments_per_image),
        seed=int(args.seed),
    )

    run_cmd(
        [
            str(args.python),
            str(scripts_dir / "train_tracker_species_onnx.py"),
            "--data-dir",
            str(mixed_root),
            "--output-onnx",
            str(onnx_path),
            "--output-labels",
            str(labels_path),
            "--output-checkpoint",
            str(ckpt_path),
            "--epochs",
            str(int(args.epochs)),
            "--batch-size",
            str(int(args.batch_size)),
            "--input-size",
            str(int(args.input_size)),
            "--num-workers",
            str(int(args.num_workers)),
            "--seed",
            str(int(args.seed)),
            "--device",
            str(args.device),
        ]
    )

    eval_manifest = str(args.eval_manifest).strip()
    if eval_manifest:
        manifest_path = Path(eval_manifest).expanduser().resolve()
        if manifest_path.exists():
            run_cmd([str(args.python), str(scripts_dir / "eval_video_species_replay.py"), str(manifest_path)])

    summary = {
        "game": cfg.game,
        "slug": cfg.slug,
        "base_scene": str(base_scene),
        "scene_count": int(len(scene_paths)),
        "real_species_count": int(len(species_ids)),
        "real_sample_policy": str(args.real_sample_policy),
        "real_species_ids": list(species_ids),
        "real_samples_total": int(real_count),
        "synthetic_samples_total": int(syn_count),
        "dataset": str(mixed_root),
        "model_onnx": str(onnx_path),
        "model_labels": str(labels_path),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
