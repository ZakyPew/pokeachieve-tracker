from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULTS: Dict[str, Any] = {
    "seed": 1337,
    "camera": {
        "source": "obs_scene",  # obs_scene | webcam
        "id": 0,
        "name": "OBS Virtual Camera",
        "prefer_obs_virtual_camera": True,
        "backend": "auto",
        "width": 1280,
        "height": 720,
        "target_fps": 20,
        "frame_skip": 0,
        "obs": {
            "host": "127.0.0.1",
            "port": 4455,
            "password": "",
            "scene_name": "Sprite Detection",
            "image_format": "jpg",
            "image_quality": 80,
        },
    },
    "runtime": {
        "mode": "roi",
        "display": True,
        "overlay": True,
        "json_output": True,
        "save_debug_frames": False,
        "debug_dir": "debug_frames",
    },
    "screen": {
        "enabled": True,
        "warp_width": 640,
        "warp_height": 480,
        "canny_low": 50,
        "canny_high": 150,
        "contour_epsilon_ratio": 0.02,
        "min_screen_area_ratio": 0.2,
        "fallback_full_frame": True,
    },
    "normalize": {
        "enabled": True,
        "clahe_clip_limit": 2.0,
        "clahe_grid_size": 8,
        "gamma": 1.0,
    },
    "roi": {
        "rois": [],
    },
    "detector": {
        "model_path": "models/detector/yolov8n_pokemon_sprite.pt",
        "conf_threshold": 0.35,
        "iou_threshold": 0.45,
        "max_detections": 6,
    },
    "embedding": {
        "model_path": "models/embedding/mobilenet_metric.pt",
        "embedding_dim": 256,
        "device": "cpu",
        "input_size": 128,
        "allow_untrained": False,
    },
    "matching": {
        "faiss_index_path": "artifacts/reference_index.faiss",
        "metadata_path": "artifacts/reference_metadata.json",
        "top_k": 5,
        "similarity_threshold": 0.62,
        "margin_threshold": 0.07,
        "unknown_label": "unknown",
    },
    "smoothing": {
        "window_size": 6,
        "min_votes": 4,
        "min_stable_confidence": 0.60,
    },
    "logging": {
        "level": "INFO",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Create one from configs/default.yaml."
        )
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return _deep_merge(DEFAULTS, loaded)


def resolve_path(base_dir: str | Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return Path(base_dir).joinpath(candidate).resolve()