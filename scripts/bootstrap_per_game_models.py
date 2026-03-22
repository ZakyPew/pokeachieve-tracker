#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class GameTrainConfig:
    game: str
    slug: str
    sprite_prefixes: str


GAME_CONFIGS: List[GameTrainConfig] = [
    GameTrainConfig("Pokemon Red", "pokemon_red", "generation_i_red_blue"),
    GameTrainConfig("Pokemon Blue", "pokemon_blue", "generation_i_red_blue"),
    GameTrainConfig("Pokemon Gold", "pokemon_gold", "generation_ii_gold"),
    GameTrainConfig("Pokemon Silver", "pokemon_silver", "generation_ii_silver"),
    GameTrainConfig("Pokemon Crystal", "pokemon_crystal", "generation_ii_gold,generation_ii_silver"),
    GameTrainConfig("Pokemon Ruby", "pokemon_ruby", "generation_iii_ruby_sapphire"),
    GameTrainConfig("Pokemon Sapphire", "pokemon_sapphire", "generation_iii_ruby_sapphire"),
    GameTrainConfig("Pokemon Emerald", "pokemon_emerald", "generation_iii_emerald,emerald"),
    GameTrainConfig("Pokemon FireRed", "pokemon_firered", "generation_iii_firered_leafgreen"),
    GameTrainConfig("Pokemon LeafGreen", "pokemon_leafgreen", "generation_iii_firered_leafgreen"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap per-game synthetic datasets and ONNX models")
    parser.add_argument("--python", type=str, default=sys.executable)
    parser.add_argument("--scenes-root", type=str, default="assets/battle_scenes")
    parser.add_argument("--datasets-root", type=str, default="debug/ai_dataset/by_game")
    parser.add_argument("--models-root", type=str, default="models/by_game")
    parser.add_argument("--samples-per-species", type=int, default=50)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--input-size", type=int, default=64)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--games", type=str, default="", help="Comma-separated game slugs to process")
    parser.add_argument("--include-gen1", action="store_true", help="Include pokemon_red and pokemon_blue in default runs")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--overwrite-datasets", action="store_true")
    return parser.parse_args()


def run_cmd(cmd: List[str]) -> None:
    print("[CMD]", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def selected_games(raw: str, include_gen1: bool = False) -> List[GameTrainConfig]:
    tokens = [token.strip().lower() for token in str(raw).split(",") if token.strip()]
    if not tokens:
        if bool(include_gen1):
            return list(GAME_CONFIGS)
        return [cfg for cfg in GAME_CONFIGS if cfg.slug not in {"pokemon_red", "pokemon_blue"}]
    wanted = set(tokens)
    return [cfg for cfg in GAME_CONFIGS if cfg.slug in wanted]


def main() -> None:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    python_bin = str(args.python)

    scenes_root = Path(args.scenes_root).resolve()
    datasets_root = Path(args.datasets_root).resolve()
    models_root = Path(args.models_root).resolve()
    datasets_root.mkdir(parents=True, exist_ok=True)
    models_root.mkdir(parents=True, exist_ok=True)

    configs = selected_games(args.games, include_gen1=bool(args.include_gen1))
    if not configs:
        raise RuntimeError("No games selected")

    summary: Dict[str, Dict[str, object]] = {}

    if not bool(args.skip_download):
        run_cmd([
            python_bin,
            str(scripts_dir / "download_battle_scenes.py"),
            "--output-root",
            str(scenes_root),
        ])

    for cfg in configs:
        game_summary: Dict[str, object] = {
            "game": cfg.game,
            "slug": cfg.slug,
            "sprite_prefixes": cfg.sprite_prefixes,
            "dataset": "",
            "model_onnx": "",
            "labels": "",
            "status": "pending",
            "error": "",
        }
        summary[cfg.slug] = game_summary

        base_image = scenes_root / cfg.slug / "base_scene.png"
        if not base_image.exists():
            game_summary["status"] = "failed"
            game_summary["error"] = f"Missing scene image: {base_image}"
            continue

        dataset_dir = datasets_root / cfg.slug / "labeled"
        model_dir = models_root / cfg.slug
        model_dir.mkdir(parents=True, exist_ok=True)
        onnx_path = model_dir / "tracker_species.onnx"
        labels_path = model_dir / "tracker_species_labels.json"
        ckpt_path = model_dir / "tracker_species.pt"
        clean_preview = datasets_root / cfg.slug / "base_clean.png"

        game_summary["dataset"] = str(dataset_dir)
        game_summary["model_onnx"] = str(onnx_path)
        game_summary["labels"] = str(labels_path)

        try:
            if bool(args.overwrite_datasets) and dataset_dir.exists():
                shutil.rmtree(dataset_dir, ignore_errors=True)

            if not bool(args.skip_generate):
                run_cmd(
                    [
                        python_bin,
                        str(scripts_dir / "generate_synthetic_emerald_dataset.py"),
                        "--base-image",
                        str(base_image),
                        "--output-dir",
                        str(dataset_dir),
                        "--sprite-prefixes",
                        str(cfg.sprite_prefixes),
                        "--samples-per-species",
                        str(int(args.samples_per_species)),
                        "--seed",
                        str(int(args.seed)),
                        "--save-base-clean",
                        str(clean_preview),
                    ]
                )

            if not bool(args.skip_train):
                run_cmd(
                    [
                        python_bin,
                        str(scripts_dir / "train_tracker_species_onnx.py"),
                        "--data-dir",
                        str(dataset_dir),
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

            game_summary["status"] = "ok"
        except subprocess.CalledProcessError as exc:
            game_summary["status"] = "failed"
            game_summary["error"] = f"Command failed ({exc.returncode})"

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
