#!/usr/bin/env python
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a single-class YOLO dataset from guided training captures."
    )
    parser.add_argument(
        "--guided-root",
        type=str,
        default=str(Path.home() / ".pokeachieve" / "guided_training"),
        help="Root guided training directory.",
    )
    parser.add_argument(
        "--game",
        type=str,
        default="pokemon_emerald",
        help="Game slug folder under guided root (for example: pokemon_emerald).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path.cwd() / "debug" / "yolo_dataset" / "pokemon_localizer"),
        help="Output YOLO dataset directory.",
    )
    parser.add_argument("--val-split", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Optional cap on number of images (0 = all).",
    )
    return parser.parse_args()


def _collect_images(game_dir: Path) -> List[Path]:
    images: List[Path] = []
    for species_dir in sorted(game_dir.glob("*")):
        if not species_dir.is_dir():
            continue
        for img in species_dir.glob("*.png"):
            images.append(img)
        for img in species_dir.glob("*.jpg"):
            images.append(img)
        for img in species_dir.glob("*.jpeg"):
            images.append(img)
    return images


def main() -> None:
    args = parse_args()
    random.seed(int(args.seed))

    guided_root = Path(str(args.guided_root)).expanduser().resolve()
    game_dir = guided_root / str(args.game).strip()
    if not game_dir.exists():
        raise SystemExit(f"Guided training game directory not found: {game_dir}")

    out_root = Path(str(args.output_dir)).expanduser().resolve()
    images_train = out_root / "images" / "train"
    images_val = out_root / "images" / "val"
    labels_train = out_root / "labels" / "train"
    labels_val = out_root / "labels" / "val"
    for p in [images_train, images_val, labels_train, labels_val]:
        p.mkdir(parents=True, exist_ok=True)

    imgs = _collect_images(game_dir)
    if not imgs:
        raise SystemExit(f"No images found under: {game_dir}")
    random.shuffle(imgs)
    if int(args.max_images) > 0:
        imgs = imgs[: int(args.max_images)]

    val_split = max(0.01, min(0.40, float(args.val_split)))
    val_count = max(1, int(len(imgs) * val_split))
    val_set = set(imgs[:val_count])

    copied = 0
    for idx, src in enumerate(imgs, start=1):
        stem = f"{src.parent.name}__{src.stem}"
        dst_img = (images_val if src in val_set else images_train) / f"{stem}{src.suffix.lower()}"
        dst_lbl = (labels_val if src in val_set else labels_train) / f"{stem}.txt"

        shutil.copy2(src, dst_img)
        # Single class (0), near-full box for guided captures.
        dst_lbl.write_text("0 0.5 0.5 0.98 0.98\n", encoding="utf-8")
        copied += 1

    yaml_path = out_root / "data.yaml"
    yaml_text = "\n".join(
        [
            f"path: {str(out_root).replace('\\', '/')}",
            "train: images/train",
            "val: images/val",
            "nc: 1",
            "names: ['pokemon']",
            "",
        ]
    )
    yaml_path.write_text(yaml_text, encoding="utf-8")

    print(f"Built YOLO dataset: {out_root}")
    print(f"Images copied: {copied} (val={val_count}, train={max(0, copied - val_count)})")
    print(f"data.yaml: {yaml_path}")


if __name__ == "__main__":
    main()
