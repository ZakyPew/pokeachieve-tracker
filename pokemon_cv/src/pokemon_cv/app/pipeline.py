from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from pokemon_cv.capture.obs_scene import OBSSceneCapture
from pokemon_cv.capture.webcam import FramePacket, WebcamCapture
from pokemon_cv.detect.base import BaseSpriteDetector
from pokemon_cv.detect.roi_detector import ROISpriteDetector
from pokemon_cv.detect.yolo_detector import YoloSpriteDetector
from pokemon_cv.embed.extractor import EmbeddingExtractor
from pokemon_cv.match.faiss_matcher import FaissSpeciesMatcher
from pokemon_cv.match.types import Candidate, CandidatePrediction, StablePrediction
from pokemon_cv.preprocess.normalize import FrameNormalizer
from pokemon_cv.preprocess.screen_rectifier import ScreenRectifier
from pokemon_cv.smooth.voting import NofMTemporalSmoother


class RuntimePipeline:
    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        config_path: str | Path,
        debug_screen: bool = False,
    ) -> None:
        self.cfg = cfg
        self.logger = logging.getLogger("pokemon_cv.pipeline")
        self.config_path = Path(config_path).resolve()
        self.debug_screen = bool(debug_screen)

        runtime_cfg = cfg.get("runtime", {})
        self.mode = str(runtime_cfg.get("mode", "roi")).lower()
        if self.mode not in {"roi", "detector"}:
            raise ValueError(f"Unsupported mode '{self.mode}'. Expected 'roi' or 'detector'.")

        self.display = bool(runtime_cfg.get("display", True))
        self.overlay = bool(runtime_cfg.get("overlay", True))
        self.json_output = bool(runtime_cfg.get("json_output", True))
        self.save_debug_frames = bool(runtime_cfg.get("save_debug_frames", False))
        self.debug_dir = Path(str(runtime_cfg.get("debug_dir", "debug_frames")))
        if self.save_debug_frames:
            self.debug_dir.mkdir(parents=True, exist_ok=True)

        camera_cfg = cfg.get("camera", {})
        self.camera_source = str(camera_cfg.get("source", "webcam")).strip().lower()
        if self.camera_source in {"obs", "obs_scene", "scene"}:
            self.capture = OBSSceneCapture(
                width=int(camera_cfg.get("width", 1280)),
                height=int(camera_cfg.get("height", 720)),
                target_fps=float(camera_cfg.get("target_fps", 20.0)),
                frame_skip=int(camera_cfg.get("frame_skip", 0)),
                obs_cfg=camera_cfg.get("obs", {}),
            )
            self.camera_source = "obs_scene"
        else:
            self.capture = WebcamCapture(
                camera_id=int(camera_cfg.get("id", 0)),
                camera_name=(None if camera_cfg.get("name") in (None, "") else str(camera_cfg.get("name"))),
                prefer_obs_virtual_camera=bool(camera_cfg.get("prefer_obs_virtual_camera", False)),
                backend=str(camera_cfg.get("backend", "auto")),
                width=int(camera_cfg.get("width", 1280)),
                height=int(camera_cfg.get("height", 720)),
                target_fps=float(camera_cfg.get("target_fps", 20.0)),
                frame_skip=int(camera_cfg.get("frame_skip", 0)),
            )
            self.camera_source = "webcam"

        self.rectifier = ScreenRectifier(cfg.get("screen", {}))
        self.normalizer = FrameNormalizer(cfg.get("normalize", {}))
        self.detector = self._build_detector()
        self.extractor = EmbeddingExtractor(cfg.get("embedding", {}))
        self.matcher = FaissSpeciesMatcher(cfg.get("matching", {}))

        smoothing_cfg = cfg.get("smoothing", {})
        self.smoother = NofMTemporalSmoother(
            window_size=int(smoothing_cfg.get("window_size", 6)),
            min_votes=int(smoothing_cfg.get("min_votes", 4)),
            min_stable_confidence=float(smoothing_cfg.get("min_stable_confidence", 0.60)),
            unknown_label=str(cfg.get("matching", {}).get("unknown_label", "unknown")),
        )
        self.unknown_label = self.smoother.unknown_label

    def _build_detector(self) -> BaseSpriteDetector:
        if self.mode == "roi":
            return ROISpriteDetector(self.cfg.get("roi", {}))
        return YoloSpriteDetector(self.cfg.get("detector", {}))

    def run(self, max_frames: int | None = None) -> None:
        self.logger.info(
            "runtime_started | mode=%s | camera_source=%s | display=%s | json_output=%s",
            self.mode,
            self.camera_source,
            self.display,
            self.json_output,
        )

        processed = 0
        try:
            for packet in self.capture.frames():
                event, display_frame = self.process_packet(packet)
                processed += 1

                if self.json_output:
                    print(json.dumps(event, separators=(",", ":")))

                frame_pred = event["frame_prediction"]
                stable_pred = event["stabilized_prediction"]
                self.logger.info(
                    "frame=%s candidates=%s raw=%s(%.3f) stable=%s(%.3f) support=%s/%s",
                    event["frame_id"],
                    len(event["candidates"]),
                    frame_pred["label"],
                    frame_pred["confidence"],
                    stable_pred["label"],
                    stable_pred["confidence"],
                    stable_pred["support_count"],
                    stable_pred["window_size"],
                )

                if self.save_debug_frames:
                    out_path = self.debug_dir / f"frame_{packet.frame_id:07d}.jpg"
                    cv2.imwrite(str(out_path), display_frame)

                if self.display:
                    cv2.imshow("pokemon-cv", display_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        self.logger.info("stop_requested | reason=user_keypress")
                        break

                if max_frames is not None and processed >= max_frames:
                    self.logger.info("stop_requested | reason=max_frames_reached | max_frames=%s", max_frames)
                    break
        finally:
            self.capture.close()
            if self.display:
                cv2.destroyAllWindows()

    def process_packet(self, packet: FramePacket) -> tuple[dict[str, Any], np.ndarray]:
        rect = self.rectifier.rectify(packet.frame_bgr)
        working_frame = self.normalizer.apply(rect.rectified_bgr)
        candidates = self.detector.detect(working_frame)

        candidate_predictions: list[CandidatePrediction] = []
        for candidate in candidates:
            crop = self._crop_candidate(working_frame, candidate)
            if crop is None:
                continue
            try:
                embedding = self.extractor.embed(crop)
                label, confidence, top_k, rejected_unknown, _reason = self.matcher.classify(embedding)
            except Exception as exc:
                self.logger.debug("candidate_embed_or_match_failed | reason=%s", exc)
                continue

            candidate_predictions.append(
                CandidatePrediction(
                    candidate=candidate,
                    top_k=top_k,
                    rejected_unknown=rejected_unknown,
                    raw_label=label,
                    raw_confidence=confidence,
                )
            )

        best_label, best_confidence = self._select_frame_prediction(candidate_predictions)
        stable = self.smoother.update(best_label, best_confidence)

        event = {
            "frame_id": packet.frame_id,
            "timestamp": packet.timestamp,
            "mode": self.mode,
            "camera_source": self.camera_source,
            "screen_found": rect.screen_found,
            "candidates": [self._candidate_to_event(cp) for cp in candidate_predictions],
            "frame_prediction": {
                "label": best_label,
                "confidence": round(best_confidence, 6),
            },
            "stabilized_prediction": self._stable_to_event(stable),
        }

        display_frame = self._render_overlay(
            frame=working_frame,
            source_frame=packet.frame_bgr,
            candidate_predictions=candidate_predictions,
            stable=stable,
            screen_found=rect.screen_found,
            corners=rect.corners,
        )
        return event, display_frame

    def _select_frame_prediction(self, candidate_predictions: list[CandidatePrediction]) -> tuple[str, float]:
        if not candidate_predictions:
            return self.unknown_label, 0.0

        best = max(
            candidate_predictions,
            key=lambda cp: (
                cp.raw_label != self.unknown_label,
                cp.raw_confidence,
                cp.candidate.score,
            ),
        )
        return best.raw_label, float(best.raw_confidence)

    @staticmethod
    def _crop_candidate(frame: np.ndarray, candidate: Candidate) -> np.ndarray | None:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = candidate.box_xyxy
        x1 = max(0, min(w - 1, int(x1)))
        y1 = max(0, min(h - 1, int(y1)))
        x2 = max(x1 + 1, min(w, int(x2)))
        y2 = max(y1 + 1, min(h, int(y2)))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        return crop

    def _render_overlay(
        self,
        *,
        frame: np.ndarray,
        source_frame: np.ndarray,
        candidate_predictions: list[CandidatePrediction],
        stable: StablePrediction,
        screen_found: bool,
        corners: np.ndarray | None,
    ) -> np.ndarray:
        vis = frame.copy()

        if self.overlay:
            for cp in candidate_predictions:
                x1, y1, x2, y2 = cp.candidate.box_xyxy
                label = cp.raw_label
                conf = cp.raw_confidence
                color = (0, 255, 0) if label != self.unknown_label else (0, 128, 255)
                cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
                text = f"{label} {conf:.2f}"
                cv2.putText(
                    vis,
                    text,
                    (x1, max(15, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                )

            stable_color = (0, 255, 0) if stable.is_stable else (0, 128, 255)
            stable_text = (
                f"stable={stable.label} conf={stable.confidence:.2f} "
                f"votes={stable.support_count}/{stable.window_size}"
            )
            cv2.putText(
                vis,
                stable_text,
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                stable_color,
                2,
            )
            cv2.putText(
                vis,
                f"screen_found={screen_found} mode={self.mode} source={self.camera_source}",
                (10, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
            )

        if self.debug_screen:
            source_debug = self.rectifier.draw_debug_overlay(source_frame, corners)
            thumb = cv2.resize(source_debug, (320, 180), interpolation=cv2.INTER_AREA)
            h, w = vis.shape[:2]
            y1 = max(0, h - thumb.shape[0])
            x1 = max(0, w - thumb.shape[1])
            vis[y1:h, x1:w] = thumb

        return vis

    @staticmethod
    def _candidate_to_event(cp: CandidatePrediction) -> dict[str, Any]:
        return {
            "box_xyxy": [int(v) for v in cp.candidate.box_xyxy],
            "detector_score": round(float(cp.candidate.score), 6),
            "source": cp.candidate.source,
            "raw_label": cp.raw_label,
            "raw_confidence": round(float(cp.raw_confidence), 6),
            "rejected_unknown": bool(cp.rejected_unknown),
            "top_k": [
                {
                    "label": m.label,
                    "species": m.species,
                    "form": m.form,
                    "shiny": bool(m.shiny),
                    "similarity": round(float(m.similarity), 6),
                    "confidence": round(float(m.confidence), 6),
                }
                for m in cp.top_k
            ],
        }

    @staticmethod
    def _stable_to_event(stable: StablePrediction) -> dict[str, Any]:
        return {
            "label": stable.label,
            "confidence": round(float(stable.confidence), 6),
            "support_count": int(stable.support_count),
            "window_size": int(stable.window_size),
            "is_stable": bool(stable.is_stable),
        }


def resolve_runtime_paths(cfg: dict[str, Any], *, config_path: str | Path) -> dict[str, Any]:
    base_dir = Path(config_path).resolve().parent

    def _resolve(section: str, key: str) -> None:
        sec = cfg.get(section, {})
        if not isinstance(sec, dict):
            return
        value = sec.get(key)
        if not isinstance(value, str) or not value:
            return
        path = Path(value)
        if path.is_absolute():
            return
        sec[key] = str((base_dir / path).resolve())

    _resolve("embedding", "model_path")
    _resolve("detector", "model_path")
    _resolve("matching", "faiss_index_path")
    _resolve("matching", "metadata_path")

    runtime = cfg.get("runtime", {})
    if isinstance(runtime, dict):
        debug_dir = runtime.get("debug_dir")
        if isinstance(debug_dir, str) and debug_dir:
            p = Path(debug_dir)
            if not p.is_absolute():
                runtime["debug_dir"] = str((base_dir / p).resolve())

    return cfg