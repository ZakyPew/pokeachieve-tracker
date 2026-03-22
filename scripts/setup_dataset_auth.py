#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write Kaggle and Roboflow API credentials for dataset downloads."
    )
    parser.add_argument("--kaggle-username", type=str, default=os.environ.get("KAGGLE_USERNAME", ""))
    parser.add_argument("--kaggle-key", type=str, default=os.environ.get("KAGGLE_KEY", ""))
    parser.add_argument("--roboflow-key", type=str, default=os.environ.get("ROBOFLOW_API_KEY", ""))
    parser.add_argument(
        "--home",
        type=str,
        default=str(Path.home()),
        help="Home directory override (advanced).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    home = Path(str(args.home)).expanduser().resolve()

    wrote_any = False

    kaggle_user = str(args.kaggle_username or "").strip()
    kaggle_key = str(args.kaggle_key or "").strip()
    if kaggle_user and kaggle_key:
        kaggle_dir = home / ".kaggle"
        kaggle_dir.mkdir(parents=True, exist_ok=True)
        kaggle_json = kaggle_dir / "kaggle.json"
        kaggle_json.write_text(
            json.dumps({"username": kaggle_user, "key": kaggle_key}, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(str(kaggle_json), 0o600)
        except Exception:
            pass
        print(f"Wrote Kaggle credentials: {kaggle_json}")
        wrote_any = True
    else:
        print("Skipped Kaggle credentials (missing username/key).")

    roboflow_key = str(args.roboflow_key or "").strip()
    if roboflow_key:
        rf_dir = home / ".roboflow"
        rf_dir.mkdir(parents=True, exist_ok=True)
        rf_file = rf_dir / "apikey.txt"
        rf_file.write_text(roboflow_key + "\n", encoding="utf-8")
        print(f"Wrote Roboflow key: {rf_file}")
        wrote_any = True
    else:
        print("Skipped Roboflow key (missing key).")

    if not wrote_any:
        raise SystemExit(
            "No credentials written. Provide --kaggle-username/--kaggle-key and/or --roboflow-key."
        )


if __name__ == "__main__":
    main()
