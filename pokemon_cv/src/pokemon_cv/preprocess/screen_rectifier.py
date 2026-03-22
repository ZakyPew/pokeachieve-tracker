from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(slots=True)
class RectificationResult:
    rectified_bgr: np.ndarray
    screen_found: bool
    corners: np.ndarray | None


class ScreenRectifier:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.enabled = bool(cfg.get("enabled", True))
        self.warp_width = int(cfg.get("warp_width", 640))
        self.warp_height = int(cfg.get("warp_height", 480))
        self.canny_low = int(cfg.get("canny_low", 50))
        self.canny_high = int(cfg.get("canny_high", 150))
        self.contour_epsilon_ratio = float(cfg.get("contour_epsilon_ratio", 0.02))
        self.min_screen_area_ratio = float(cfg.get("min_screen_area_ratio", 0.2))
        self.fallback_full_frame = bool(cfg.get("fallback_full_frame", True))

    def rectify(self, frame_bgr: np.ndarray) -> RectificationResult:
        if (not self.enabled) or frame_bgr is None or frame_bgr.size == 0:
            return RectificationResult(
                rectified_bgr=cv2.resize(frame_bgr, (self.warp_width, self.warp_height)),
                screen_found=False,
                corners=None,
            )

        corners = self._detect_screen_corners(frame_bgr)
        if corners is None:
            if self.fallback_full_frame:
                rectified = cv2.resize(frame_bgr, (self.warp_width, self.warp_height))
            else:
                rectified = frame_bgr.copy()
            return RectificationResult(rectified_bgr=rectified, screen_found=False, corners=None)

        warped = self._warp(frame_bgr, corners)
        return RectificationResult(rectified_bgr=warped, screen_found=True, corners=corners)

    def draw_debug_overlay(self, frame_bgr: np.ndarray, corners: np.ndarray | None) -> np.ndarray:
        vis = frame_bgr.copy()
        if corners is None:
            cv2.putText(vis, "screen: not found", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return vis

        pts = corners.astype(np.int32)
        cv2.polylines(vis, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        for i, (x, y) in enumerate(pts):
            cv2.circle(vis, (int(x), int(y)), 5, (255, 0, 0), -1)
            cv2.putText(vis, str(i), (int(x) + 6, int(y) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(vis, "screen: found", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        return vis

    def _detect_screen_corners(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        h, w = frame_bgr.shape[:2]
        min_area = float(h * w) * self.min_screen_area_ratio

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, self.canny_low, self.canny_high)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, self.contour_epsilon_ratio * peri, True)
            if len(approx) != 4:
                continue
            pts = approx.reshape(4, 2).astype(np.float32)
            return self._order_points(pts)
        return None

    def _warp(self, frame_bgr: np.ndarray, corners: np.ndarray) -> np.ndarray:
        dst = np.array(
            [
                [0, 0],
                [self.warp_width - 1, 0],
                [self.warp_width - 1, self.warp_height - 1],
                [0, self.warp_height - 1],
            ],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
        return cv2.warpPerspective(frame_bgr, matrix, (self.warp_width, self.warp_height))

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        # tl, tr, br, bl
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        ordered = np.zeros((4, 2), dtype=np.float32)
        ordered[0] = pts[np.argmin(s)]
        ordered[2] = pts[np.argmax(s)]
        ordered[1] = pts[np.argmin(diff)]
        ordered[3] = pts[np.argmax(diff)]
        return ordered
