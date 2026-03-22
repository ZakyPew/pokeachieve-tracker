from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pokemon_cv.detect.base import BaseSpriteDetector
from pokemon_cv.match.types import Candidate


@dataclass(slots=True)
class ROI:
    name: str
    x: float
    y: float
    w: float
    h: float


class ROISpriteDetector(BaseSpriteDetector):
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.rois: list[ROI] = []
        for raw in cfg.get("rois", []):
            if not isinstance(raw, dict):
                continue
            self.rois.append(
                ROI(
                    name=str(raw.get("name", "roi")),
                    x=float(raw.get("x", 0.0)),
                    y=float(raw.get("y", 0.0)),
                    w=float(raw.get("w", 1.0)),
                    h=float(raw.get("h", 1.0)),
                )
            )

    def detect(self, frame_bgr: np.ndarray) -> list[Candidate]:
        if frame_bgr is None or frame_bgr.size == 0:
            return []
        h, w = frame_bgr.shape[:2]
        detections: list[Candidate] = []
        for roi in self.rois:
            x1 = int(max(0, min(w - 1, round(roi.x * w))))
            y1 = int(max(0, min(h - 1, round(roi.y * h))))
            x2 = int(max(x1 + 1, min(w, round((roi.x + roi.w) * w))))
            y2 = int(max(y1 + 1, min(h, round((roi.y + roi.h) * h))))
            detections.append(
                Candidate(box_xyxy=(x1, y1, x2, y2), score=1.0, source=f"roi:{roi.name}")
            )
        return detections
