#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO detector (single class: pokemon_sprite)")
    parser.add_argument("--data-yaml", type=str, required=True, help="Ultralytics data.yaml path")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Base model checkpoint")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--project", type=str, default="runs/pokemon_detector")
    parser.add_argument("--name", type=str, default="yolov8n_sprite")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.train_detector")

    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Ultralytics is required for detector training. Install with `pip install ultralytics`."
        ) from exc

    data_yaml = Path(args.data_yaml).resolve()
    if not data_yaml.exists():
        raise FileNotFoundError(f"data.yaml not found: {data_yaml}")

    logger.info(
        "detector_train_start | model=%s | data=%s | epochs=%s | imgsz=%s",
        args.model,
        data_yaml,
        args.epochs,
        args.imgsz,
    )

    model = YOLO(args.model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
    )

    logger.info("detector_train_done | project=%s | name=%s", args.project, args.name)


if __name__ == "__main__":
    main()