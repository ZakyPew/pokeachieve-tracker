#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a single-class YOLO localizer for Pokemon battle sprites."
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="Path to YOLO data.yaml (train/val image + label paths).",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="yolov8n.pt",
        help="Base Ultralytics checkpoint (default: yolov8n.pt).",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument(
        "--project",
        type=str,
        default="runs/pokemon_localizer",
        help="Output project directory.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="train",
        help="Run name under project.",
    )
    parser.add_argument(
        "--single-cls",
        action="store_true",
        default=True,
        help="Force single-class training (enabled by default).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "Ultralytics is required. Install with: pip install ultralytics"
        ) from exc

    data_path = Path(str(args.data)).expanduser().resolve()
    if not data_path.exists():
        raise SystemExit(f"data.yaml not found: {data_path}")

    model = YOLO(str(args.weights))
    model.train(
        data=str(data_path),
        epochs=int(args.epochs),
        imgsz=int(args.imgsz),
        batch=int(args.batch),
        device=str(args.device),
        project=str(args.project),
        name=str(args.name),
        single_cls=bool(args.single_cls),
    )

    runs_dir = Path(str(args.project)).expanduser().resolve()
    run_dir = runs_dir / str(args.name)
    best = run_dir / "weights" / "best.pt"
    print(f"Training complete. Best weights (expected): {best}")
    print(
        "Set tracker config key `video_yolo_model_path` to that best.pt path."
    )


if __name__ == "__main__":
    main()
