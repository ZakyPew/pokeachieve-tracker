from __future__ import annotations

from typing import Any

import cv2
import numpy as np


class FrameNormalizer:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.enabled = bool(cfg.get("enabled", True))
        self.clahe_clip_limit = float(cfg.get("clahe_clip_limit", 2.0))
        self.clahe_grid_size = int(cfg.get("clahe_grid_size", 8))
        self.gamma = float(cfg.get("gamma", 1.0))

    def apply(self, frame_bgr: np.ndarray) -> np.ndarray:
        if (not self.enabled) or frame_bgr is None or frame_bgr.size == 0:
            return frame_bgr

        lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=max(0.1, self.clahe_clip_limit),
            tileGridSize=(max(1, self.clahe_grid_size), max(1, self.clahe_grid_size)),
        )
        l2 = clahe.apply(l)
        merged = cv2.merge((l2, a, b))
        out = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

        if abs(self.gamma - 1.0) > 1e-3:
            out = self._gamma_correct(out, self.gamma)
        return out

    @staticmethod
    def _gamma_correct(img_bgr: np.ndarray, gamma: float) -> np.ndarray:
        gamma = max(0.1, min(4.0, float(gamma)))
        inv = 1.0 / gamma
        table = np.array([(i / 255.0) ** inv * 255 for i in range(256)]).astype("uint8")
        return cv2.LUT(img_bgr, table)
