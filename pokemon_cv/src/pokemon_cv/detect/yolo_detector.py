from __future__ import annotations

from typing import Any

import numpy as np

from pokemon_cv.detect.base import BaseSpriteDetector
from pokemon_cv.match.types import Candidate


class YoloSpriteDetector(BaseSpriteDetector):
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.model_path = str(cfg.get("model_path", ""))
        self.conf_threshold = float(cfg.get("conf_threshold", 0.35))
        self.iou_threshold = float(cfg.get("iou_threshold", 0.45))
        self.max_detections = int(cfg.get("max_detections", 6))

        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Ultralytics is required for detector mode. Install with `pip install ultralytics`."
            ) from exc

        self._model = YOLO(self.model_path)

    def detect(self, frame_bgr: np.ndarray) -> list[Candidate]:
        results = self._model.predict(
            source=frame_bgr,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            verbose=False,
            max_det=self.max_detections,
        )
        if not results:
            return []

        out: list[Candidate] = []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return out

        for b in boxes:
            xyxy = b.xyxy[0].tolist()
            conf = float(b.conf[0].item())
            x1, y1, x2, y2 = [int(max(0, round(v))) for v in xyxy]
            out.append(Candidate(box_xyxy=(x1, y1, x2, y2), score=conf, source="detector:yolo"))
        return out
