from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any, Generator

import cv2
import numpy as np

from pokemon_cv.capture.webcam import FramePacket


@dataclass(slots=True)
class OBSSceneConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    scene_name: str = "Scene"
    image_format: str = "jpg"
    image_quality: int = 80


class OBSSceneCapture:
    """Capture frames directly from an OBS scene using OBS WebSocket screenshots."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        target_fps: float,
        frame_skip: int = 0,
        obs_cfg: dict[str, Any] | None = None,
    ) -> None:
        self.logger = logging.getLogger("pokemon_cv.capture.obs")
        cfg = obs_cfg or {}

        self.width = int(width)
        self.height = int(height)
        self.target_fps = max(1.0, float(target_fps))
        self.frame_skip = max(0, int(frame_skip))

        self.obs = OBSSceneConfig(
            host=str(cfg.get("host", "127.0.0.1")),
            port=int(cfg.get("port", 4455)),
            password=str(cfg.get("password", "")),
            scene_name=str(cfg.get("scene_name", "Scene")),
            image_format=str(cfg.get("image_format", "jpg")).lower(),
            image_quality=int(cfg.get("image_quality", 80)),
        )

        self._client: Any | None = None
        self._next_frame_id = 0

    def open(self) -> None:
        try:
            import obsws_python as obs  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "obsws-python is required for camera.source=obs_scene. Install with `pip install obsws-python`."
            ) from exc

        try:
            self._client = obs.ReqClient(
                host=self.obs.host,
                port=self.obs.port,
                password=self.obs.password,
                timeout=3,
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to connect to OBS WebSocket "
                f"at {self.obs.host}:{self.obs.port}. "
                "Enable OBS WebSocket in OBS (Tools > WebSocket Server Settings)."
            ) from exc

        self.logger.info(
            "obs_scene_connected | host=%s | port=%s | scene_name=%s | format=%s",
            self.obs.host,
            self.obs.port,
            self.obs.scene_name,
            self.obs.image_format,
        )

    def close(self) -> None:
        self._client = None

    def frames(self) -> Generator[FramePacket, None, None]:
        if self._client is None:
            self.open()
        if self._client is None:
            raise RuntimeError("OBS capture is not initialized")

        frame_interval = 1.0 / self.target_fps
        last_emit = 0.0

        try:
            while True:
                frame = self._pull_frame()
                if frame is None:
                    continue

                for _ in range(self.frame_skip):
                    _ = self._pull_frame()

                now = time.perf_counter()
                elapsed = now - last_emit
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
                    now = time.perf_counter()

                self._next_frame_id += 1
                last_emit = now
                yield FramePacket(
                    frame_id=self._next_frame_id,
                    timestamp=time.time(),
                    frame_bgr=frame,
                )
        finally:
            self.close()

    def _pull_frame(self) -> np.ndarray | None:
        if self._client is None:
            return None

        try:
            resp = self._client.get_source_screenshot(
                sourceName=self.obs.scene_name,
                imageFormat=self.obs.image_format,
                imageWidth=max(1, self.width),
                imageHeight=max(1, self.height),
                imageCompressionQuality=max(1, min(100, self.obs.image_quality)),
            )
        except Exception as exc:
            self.logger.debug("obs_screenshot_failed | reason=%s", exc)
            return None

        image_data = getattr(resp, "image_data", None)
        if image_data is None:
            image_data = getattr(resp, "imageData", None)
        if not isinstance(image_data, str) or not image_data:
            return None

        payload = image_data.split(",", 1)[1] if "," in image_data else image_data
        try:
            blob = base64.b64decode(payload)
        except Exception:
            return None

        arr = np.frombuffer(blob, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return None
        return frame