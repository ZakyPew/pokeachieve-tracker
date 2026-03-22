#!/usr/bin/env python
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge YOLO datasets into one single-class (class=0) dataset."
    )
    parser.add_argument("--kaggle-root", type=str, required=True, help="Root folder containing train/val/test flat files.")
    parser.add_argument(
        "--guided-yolo-root",
        type=str,
        default="",
        help="Optional YOLO root with images/{train,val} + labels/{train,val}.",
    )
    parser.add_argument("--output-root", type=str, required=True, help="Output YOLO dataset root.")
    return parser.parse_args()


def _safe_name(prefix: str, stem: str) -> str:
    return f"{prefix}__{stem}"


def _read_single_cls_label(src: Path) -> str:
    lines_out = []
    try:
        lines = src.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    for line in lines:
        row = str(line).strip()
        if not row:
            continue
        parts = row.split()
        if len(parts) < 5:
            continue
        parts[0] = "0"
        lines_out.append(" ".join(parts[:5]))
    if not lines_out:
        # Fallback box if source label is empty/corrupt.
        return "0 0.5 0.5 0.98 0.98\n"
    return "\n".join(lines_out) + "\n"


def _iter_flat_pairs(split_dir: Path) -> Iterable[Tuple[Path, Path]]:
    for img in split_dir.iterdir():
        if not img.is_file():
            continue
        if img.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            continue
        lbl = img.with_suffix(".txt")
        if lbl.exists():
            yield img, lbl


def _iter_yolo_pairs(images_dir: Path, labels_dir: Path) -> Iterable[Tuple[Path, Path]]:
    if not images_dir.exists() or not labels_dir.exists():
        return
    for img in images_dir.rglob("*"):
        if not img.is_file():
            continue
        if img.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            continue
        rel = img.relative_to(images_dir)
        lbl = labels_dir / rel.with_suffix(".txt")
        if lbl.exists():
            yield img, lbl


def _copy_pair(img: Path, lbl: Path, out_img_dir: Path, out_lbl_dir: Path, prefix: str) -> int:
    out_name = _safe_name(prefix, img.stem)
    dst_img = out_img_dir / f"{out_name}{img.suffix.lower()}"
    dst_lbl = out_lbl_dir / f"{out_name}.txt"
    shutil.copy2(img, dst_img)
    dst_lbl.write_text(_read_single_cls_label(lbl), encoding="utf-8")
    return 1


def main() -> None:
    args = parse_args()
    kaggle_root = Path(str(args.kaggle_root)).expanduser().resolve()
    guided_root = Path(str(args.guided_yolo_root)).expanduser().resolve() if str(args.guided_yolo_root).strip() else None
    out_root = Path(str(args.output_root)).expanduser().resolve()

    train_img = out_root / "images" / "train"
    val_img = out_root / "images" / "val"
    train_lbl = out_root / "labels" / "train"
    val_lbl = out_root / "labels" / "val"
    for p in [train_img, val_img, train_lbl, val_lbl]:
        p.mkdir(parents=True, exist_ok=True)

    n_train = 0
    n_val = 0

    # Kaggle flat structure.
    kaggle_train = kaggle_root / "train"
    kaggle_val = kaggle_root / "val"
    kaggle_test = kaggle_root / "test"
    for img, lbl in _iter_flat_pairs(kaggle_train):
        n_train += _copy_pair(img, lbl, train_img, train_lbl, "kaggle_train")
    for img, lbl in _iter_flat_pairs(kaggle_val):
        n_val += _copy_pair(img, lbl, val_img, val_lbl, "kaggle_val")
    for img, lbl in _iter_flat_pairs(kaggle_test):
        n_val += _copy_pair(img, lbl, val_img, val_lbl, "kaggle_test")

    # Optional guided YOLO structure.
    if isinstance(guided_root, Path) and guided_root.exists():
        for img, lbl in _iter_yolo_pairs(guided_root / "images" / "train", guided_root / "labels" / "train"):
            n_train += _copy_pair(img, lbl, train_img, train_lbl, "guided_train")
        for img, lbl in _iter_yolo_pairs(guided_root / "images" / "val", guided_root / "labels" / "val"):
            n_val += _copy_pair(img, lbl, val_img, val_lbl, "guided_val")

    yaml_path = out_root / "data.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {str(out_root).replace(chr(92), '/')}",
                "train: images/train",
                "val: images/val",
                "nc: 1",
                "names: ['pokemon']",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Merged dataset root: {out_root}")
    print(f"Train images: {n_train}")
    print(f"Val images: {n_val}")
    print(f"data.yaml: {yaml_path}")


if __name__ == "__main__":
    main()
