from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Generator, Sequence

import cv2
import numpy as np


@dataclass(slots=True)
class FramePacket:
    frame_id: int
    timestamp: float
    frame_bgr: np.ndarray


@dataclass(slots=True)
class CameraDevice:
    index: int
    name: str


def enumerate_camera_devices() -> list[CameraDevice]:
    """Best-effort Windows camera enumeration using DirectShow names."""
    try:
        from pygrabber.dshow_graph import FilterGraph  # type: ignore

        names = FilterGraph().get_input_devices()
        return [CameraDevice(index=i, name=str(name)) for i, name in enumerate(names)]
    except Exception:
        return []


def choose_camera_index(
    *,
    camera_id: int,
    camera_name: str | None,
    prefer_obs_virtual_camera: bool,
    devices: Sequence[CameraDevice],
) -> tuple[int, str | None]:
    selected_id = int(camera_id)
    selected_name: str | None = None

    requested_name = (camera_name or "").strip().lower()

    if requested_name:
        for dev in devices:
            if dev.name.strip().lower() == requested_name:
                return dev.index, dev.name
        for dev in devices:
            if requested_name in dev.name.strip().lower():
                return dev.index, dev.name

    if prefer_obs_virtual_camera:
        for token in ("obs virtual camera", "obs"):
            for dev in devices:
                if token in dev.name.strip().lower():
                    return dev.index, dev.name

    return selected_id, selected_name


class WebcamCapture:
    def __init__(
        self,
        camera_id: int,
        width: int,
        height: int,
        target_fps: float,
        frame_skip: int = 0,
        camera_name: str | None = None,
        prefer_obs_virtual_camera: bool = False,
        backend: str = "auto",
    ) -> None:
        self.logger = logging.getLogger("pokemon_cv.capture")

        self.camera_id = int(camera_id)
        self.camera_name = (camera_name or "").strip() or None
        self.prefer_obs_virtual_camera = bool(prefer_obs_virtual_camera)
        self.backend = str(backend or "auto").strip().lower()

        self.width = int(width)
        self.height = int(height)
        self.target_fps = max(1.0, float(target_fps))
        self.frame_skip = max(0, int(frame_skip))

        self._cap: cv2.VideoCapture | None = None
        self._next_frame_id = 0
        self._resolved_camera_id: int = self.camera_id
        self._resolved_camera_name: str | None = None

    @property
    def resolved_camera_id(self) -> int:
        return self._resolved_camera_id

    @property
    def resolved_camera_name(self) -> str | None:
        return self._resolved_camera_name

    def open(self) -> None:
        devices = enumerate_camera_devices()
        resolved_id, resolved_name = choose_camera_index(
            camera_id=self.camera_id,
            camera_name=self.camera_name,
            prefer_obs_virtual_camera=self.prefer_obs_virtual_camera,
            devices=devices,
        )
        self._resolved_camera_id = int(resolved_id)
        self._resolved_camera_name = resolved_name

        cap = self._open_capture(self._resolved_camera_id)
        if not cap.isOpened():
            raise RuntimeError(
                "Failed to open webcam "
                f"id={self._resolved_camera_id} "
                f"(requested_id={self.camera_id}, requested_name={self.camera_name}). "
                "If using OBS Virtual Camera, ensure OBS virtual camera is started and try scripts/list_cameras.py."
            )

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap = cap

        self.logger.info(
            "camera_opened | requested_id=%s | requested_name=%s | prefer_obs=%s | resolved_id=%s | resolved_name=%s | backend=%s",
            self.camera_id,
            self.camera_name,
            self.prefer_obs_virtual_camera,
            self._resolved_camera_id,
            self._resolved_camera_name,
            self.backend,
        )

    def _open_capture(self, camera_id: int) -> cv2.VideoCapture:
        backend = self.backend
        if backend == "dshow":
            cap_dshow = getattr(cv2, "CAP_DSHOW", None)
            if cap_dshow is not None:
                return cv2.VideoCapture(camera_id, cap_dshow)
            return cv2.VideoCapture(camera_id)

        if backend == "msmf":
            cap_msmf = getattr(cv2, "CAP_MSMF", None)
            if cap_msmf is not None:
                return cv2.VideoCapture(camera_id, cap_msmf)
            return cv2.VideoCapture(camera_id)

        # auto: prefer DirectShow on Windows for OBS Virtual Camera, fallback to default backend.
        cap_dshow = getattr(cv2, "CAP_DSHOW", None)
        if cap_dshow is not None:
            cap = cv2.VideoCapture(camera_id, cap_dshow)
            if cap.isOpened():
                return cap
            cap.release()

        return cv2.VideoCapture(camera_id)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def frames(self) -> Generator[FramePacket, None, None]:
        if self._cap is None:
            self.open()
        if self._cap is None:
            raise RuntimeError("Capture is not initialized")

        frame_interval = 1.0 / self.target_fps
        last_emit = 0.0

        try:
            while True:
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    continue

                for _ in range(self.frame_skip):
                    _ok, _ = self._cap.read()
                    if not _ok:
                        break

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