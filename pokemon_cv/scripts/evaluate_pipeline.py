#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.app.pipeline import resolve_runtime_paths
from pokemon_cv.config import load_config
from pokemon_cv.detect.base import BaseSpriteDetector
from pokemon_cv.detect.roi_detector import ROISpriteDetector
from pokemon_cv.detect.yolo_detector import YoloSpriteDetector
from pokemon_cv.embed.dataset import iter_image_files
from pokemon_cv.embed.extractor import EmbeddingExtractor
from pokemon_cv.match.faiss_matcher import FaissSpeciesMatcher
from pokemon_cv.match.types import Candidate
from pokemon_cv.preprocess.normalize import FrameNormalizer
from pokemon_cv.preprocess.screen_rectifier import ScreenRectifier
from pokemon_cv.utils.logging import setup_logging


class FullFrameDetector(BaseSpriteDetector):
    def detect(self, frame_bgr: np.ndarray) -> list[Candidate]:
        h, w = frame_bgr.shape[:2]
        return [Candidate(box_xyxy=(0, 0, w, h), score=1.0, source="full_frame")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate matcher pipeline on labeled test images")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--dataset-dir", type=str, required=True, help="Labeled eval set root (class folders)")
    parser.add_argument("--output-dir", type=str, default="artifacts/eval")
    parser.add_argument("--input-mode", type=str, choices=["crop", "roi", "detector"], default="crop")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--unknown-label", type=str, default="unknown")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def select_best_label(
    frame: np.ndarray,
    detector: BaseSpriteDetector,
    extractor: EmbeddingExtractor,
    matcher: FaissSpeciesMatcher,
    unknown_label: str,
) -> tuple[str, float, list[str]]:
    candidates = detector.detect(frame)
    if not candidates:
        return unknown_label, 0.0, []

    best_label = unknown_label
    best_conf = 0.0
    best_topk: list[str] = []

    h, w = frame.shape[:2]
    for c in candidates:
        x1, y1, x2, y2 = c.box_xyxy
        x1 = max(0, min(w - 1, int(x1)))
        y1 = max(0, min(h - 1, int(y1)))
        x2 = max(x1 + 1, min(w, int(x2)))
        y2 = max(y1 + 1, min(h, int(y2)))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        embedding = extractor.embed(crop)
        label, conf, top_k, _is_unknown, _reason = matcher.classify(embedding)
        topk_labels = [m.label for m in top_k]

        score_key = (label != unknown_label, conf, c.score)
        best_key = (best_label != unknown_label, best_conf, 0.0)
        if score_key > best_key:
            best_label = label
            best_conf = float(conf)
            best_topk = topk_labels

    return best_label, best_conf, best_topk


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.evaluate")

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)
    cfg = resolve_runtime_paths(cfg, config_path=cfg_path)

    dataset_dir = Path(args.dataset_dir).resolve()
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_dir}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rectifier = ScreenRectifier(cfg.get("screen", {}))
    normalizer = FrameNormalizer(cfg.get("normalize", {}))
    extractor = EmbeddingExtractor(cfg.get("embedding", {}))
    matcher = FaissSpeciesMatcher(cfg.get("matching", {}))

    detector: BaseSpriteDetector
    if args.input_mode == "crop":
        detector = FullFrameDetector()
    elif args.input_mode == "roi":
        detector = ROISpriteDetector(cfg.get("roi", {}))
    else:
        detector = YoloSpriteDetector(cfg.get("detector", {}))

    image_paths = iter_image_files(dataset_dir)
    if args.max_samples > 0:
        image_paths = image_paths[: args.max_samples]
    if not image_paths:
        raise RuntimeError("No images found in eval set")

    unknown_label = args.unknown_label.strip().lower()

    total = 0
    known_total = 0
    top1_correct = 0
    top3_correct = 0
    unknown_fp_count = 0
    latencies_ms: list[float] = []

    y_true: list[str] = []
    y_pred: list[str] = []

    for image_path in image_paths:
        true_label = image_path.parent.name.strip().lower()
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            logger.warning("skip_invalid_image | path=%s", image_path)
            continue

        t0 = time.perf_counter()

        if args.input_mode == "crop":
            working = normalizer.apply(image)
        else:
            rect = rectifier.rectify(image)
            working = normalizer.apply(rect.rectified_bgr)

        pred_label, pred_conf, topk_labels = select_best_label(
            working,
            detector,
            extractor,
            matcher,
            unknown_label=unknown_label,
        )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(latency_ms)

        total += 1
        y_true.append(true_label)
        y_pred.append(pred_label)

        is_known = true_label != unknown_label
        if is_known:
            known_total += 1
            if pred_label == unknown_label:
                unknown_fp_count += 1

        if pred_label == true_label:
            top1_correct += 1
        if true_label in topk_labels[:3]:
            top3_correct += 1

        logger.info(
            "eval_sample | file=%s | true=%s | pred=%s | conf=%.3f | latency_ms=%.2f",
            image_path.name,
            true_label,
            pred_label,
            pred_conf,
            latency_ms,
        )

    labels = sorted(set(y_true) | set(y_pred))
    matrix: dict[str, dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        matrix[t][p] += 1

    cm_path = output_dir / "confusion_matrix.csv"
    with cm_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["true\\pred", *labels])
        for t in labels:
            writer.writerow([t, *[matrix[t][p] for p in labels]])

    top1 = float(top1_correct / total) if total else 0.0
    top3 = float(top3_correct / total) if total else 0.0
    unknown_fp_rate = float(unknown_fp_count / known_total) if known_total else 0.0
    latency_mean = float(np.mean(latencies_ms)) if latencies_ms else 0.0
    latency_p95 = float(np.percentile(latencies_ms, 95)) if latencies_ms else 0.0

    report = {
        "samples": total,
        "known_samples": known_total,
        "top1_accuracy": top1,
        "top3_accuracy": top3,
        "unknown_false_positive_rate": unknown_fp_rate,
        "latency_ms_mean": latency_mean,
        "latency_ms_p95": latency_p95,
        "confusion_matrix_csv": str(cm_path),
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info(
        "eval_done | samples=%s | top1=%.4f | top3=%.4f | unknown_fp=%.4f | latency_ms_mean=%.2f | latency_ms_p95=%.2f",
        total,
        top1,
        top3,
        unknown_fp_rate,
        latency_mean,
        latency_p95,
    )
    logger.info("artifacts | report=%s | confusion=%s", report_path, cm_path)


if __name__ == "__main__":
    main()