#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List OBS scenes via WebSocket")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--password", type=str, default="")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.list_obs_scenes")

    try:
        import obsws_python as obs  # type: ignore
    except Exception as exc:
        raise RuntimeError("obsws-python is required. Install with `pip install obsws-python`.") from exc

    client = obs.ReqClient(host=args.host, port=args.port, password=args.password, timeout=3)
    scenes_resp = client.get_scene_list()
    current = getattr(scenes_resp, "current_program_scene_name", None) or getattr(scenes_resp, "currentProgramSceneName", "")

    raw_scenes = getattr(scenes_resp, "scenes", [])
    names: list[str] = []
    for s in raw_scenes:
        if isinstance(s, dict):
            names.append(str(s.get("sceneName", "")))
        else:
            names.append(str(getattr(s, "sceneName", "")))

    logger.info("obs_connected | host=%s | port=%s | current_scene=%s", args.host, args.port, current)
    print(json.dumps({"current_scene": current, "scenes": names}, indent=2))


if __name__ == "__main__":
    main()