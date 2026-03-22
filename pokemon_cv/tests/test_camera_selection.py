from __future__ import annotations

from pokemon_cv.capture.webcam import CameraDevice, choose_camera_index


def test_choose_camera_exact_name_match() -> None:
    devices = [
        CameraDevice(index=0, name="Integrated Webcam"),
        CameraDevice(index=1, name="OBS Virtual Camera"),
    ]
    idx, name = choose_camera_index(
        camera_id=0,
        camera_name="OBS Virtual Camera",
        prefer_obs_virtual_camera=False,
        devices=devices,
    )
    assert idx == 1
    assert name == "OBS Virtual Camera"


def test_choose_camera_obs_preference_fallback() -> None:
    devices = [
        CameraDevice(index=0, name="Integrated Webcam"),
        CameraDevice(index=2, name="OBS Virtual Camera"),
    ]
    idx, name = choose_camera_index(
        camera_id=0,
        camera_name=None,
        prefer_obs_virtual_camera=True,
        devices=devices,
    )
    assert idx == 2
    assert name == "OBS Virtual Camera"


def test_choose_camera_defaults_to_id() -> None:
    devices = [CameraDevice(index=0, name="Integrated Webcam")]
    idx, name = choose_camera_index(
        camera_id=3,
        camera_name="nonexistent",
        prefer_obs_virtual_camera=False,
        devices=devices,
    )
    assert idx == 3
    assert name is None