#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.capture.webcam import enumerate_camera_devices
from pokemon_cv.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List available webcam devices")
    parser.add_argument("--max-index", type=int, default=10, help="Probe camera indexes [0..max-index]")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.list_cameras")

    named = [{"index": d.index, "name": d.name} for d in enumerate_camera_devices()]

    probes = []
    for idx in range(max(0, args.max_index) + 1):
        cap = cv2.VideoCapture(idx)
        opened = bool(cap.isOpened())
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if opened else 0
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if opened else 0
        if opened:
            cap.release()
        probes.append({"index": idx, "opened": opened, "width": width, "height": height})

    payload = {"named_devices": named, "probe_results": probes}
    logger.info("camera_scan_complete | named=%s | probes=%s", len(named), len(probes))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()