from __future__ import annotations

import argparse
import copy
import logging
import random
from pathlib import Path

import numpy as np
import torch

from pokemon_cv.app.pipeline import RuntimePipeline, resolve_runtime_paths
from pokemon_cv.config import load_config
from pokemon_cv.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time Pokemon sprite detection and recognition")
    parser.add_argument("--config", type=str, default="configs/default.yaml", help="Path to YAML config")
    parser.add_argument("--mode", type=str, choices=["roi", "detector"], help="Override runtime mode")

    parser.add_argument("--camera-source", type=str, choices=["webcam", "obs_scene"], help="Input source backend")
    parser.add_argument("--camera-id", type=int, help="Webcam id")
    parser.add_argument("--camera-name", type=str, help="Preferred webcam device name (e.g. OBS Virtual Camera)")
    parser.add_argument("--prefer-obs", action="store_true", help="Prefer OBS Virtual Camera when using webcam source")
    parser.add_argument("--camera-backend", type=str, choices=["auto", "dshow", "msmf"], help="OpenCV webcam backend")

    parser.add_argument("--obs-scene", type=str, help="OBS scene name when camera-source=obs_scene")
    parser.add_argument("--obs-host", type=str, help="OBS WebSocket host")
    parser.add_argument("--obs-port", type=int, help="OBS WebSocket port")
    parser.add_argument("--obs-password", type=str, help="OBS WebSocket password")

    parser.add_argument("--width", type=int, help="Capture width")
    parser.add_argument("--height", type=int, help="Capture height")
    parser.add_argument("--fps", type=float, help="Target FPS")
    parser.add_argument("--frame-skip", type=int, help="Number of frames to skip between processed frames")
    parser.add_argument("--max-frames", type=int, help="Stop after processing N frames")
    parser.add_argument("--no-display", action="store_true", help="Disable OpenCV window")
    parser.add_argument("--no-json", action="store_true", help="Disable JSON frame event output")
    parser.add_argument("--debug-screen", action="store_true", help="Render original-frame screen-corner debug thumbnail")
    parser.add_argument("--seed", type=int, help="Random seed")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def apply_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    out = copy.deepcopy(cfg)
    runtime = out.setdefault("runtime", {})
    camera = out.setdefault("camera", {})
    obs = camera.setdefault("obs", {})

    if args.mode:
        runtime["mode"] = args.mode
    if args.no_display:
        runtime["display"] = False
    if args.no_json:
        runtime["json_output"] = False

    if args.camera_source is not None:
        camera["source"] = args.camera_source
    if args.camera_id is not None:
        camera["id"] = args.camera_id
    if args.camera_name is not None:
        camera["name"] = args.camera_name
    if args.prefer_obs:
        camera["prefer_obs_virtual_camera"] = True
    if args.camera_backend is not None:
        camera["backend"] = args.camera_backend

    if args.obs_scene is not None:
        obs["scene_name"] = args.obs_scene
    if args.obs_host is not None:
        obs["host"] = args.obs_host
    if args.obs_port is not None:
        obs["port"] = args.obs_port
    if args.obs_password is not None:
        obs["password"] = args.obs_password

    if args.width is not None:
        camera["width"] = args.width
    if args.height is not None:
        camera["height"] = args.height
    if args.fps is not None:
        camera["target_fps"] = args.fps
    if args.frame_skip is not None:
        camera["frame_skip"] = args.frame_skip

    if args.seed is not None:
        out["seed"] = args.seed

    return out


def main() -> None:
    args = parse_args()
    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)
    cfg = apply_overrides(cfg, args)
    cfg = resolve_runtime_paths(cfg, config_path=cfg_path)

    setup_logging(cfg.get("logging", {}).get("level", "INFO"))
    logger = logging.getLogger("pokemon_cv.cli")

    seed = int(cfg.get("seed", 1337))
    set_seed(seed)
    logger.info("seed_set | seed=%s", seed)

    pipeline = RuntimePipeline(cfg, config_path=cfg_path, debug_screen=args.debug_screen)
    try:
        pipeline.run(max_frames=args.max_frames)
    except KeyboardInterrupt:
        logger.info("stopped | reason=keyboard_interrupt")


if __name__ == "__main__":
    main()