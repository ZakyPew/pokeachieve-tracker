# Pokemon CV

Production-oriented Python project for real-time Pokemon recognition, focused on 2D game sprites and robust unknown rejection.

Primary input path: **OBS scene capture via OBS WebSocket** (not required to use Windows webcam device).

## Features

- Real-time frame ingest from either:
  - `obs_scene` (primary): pull frames directly from a named OBS scene
  - `webcam` (fallback): OpenCV camera input (can target OBS Virtual Camera)
- Stage A: game-screen detection + perspective warp to canonical size.
- Stage B: candidate extraction via:
  - ROI mode (known layouts)
  - detector mode (YOLO, single class: `pokemon_sprite`)
- Stage C: embedding-based matching against reference sprites using FAISS cosine search.
- Stage D: temporal N-of-M stabilization (`4-of-6` default).
- Per-frame JSON event output and optional OpenCV overlay.

## Repository Layout

```text
pokemon_cv/
  configs/
    default.yaml
  scripts/
    build_reference_index.py
    train_embedding_model.py
    train_detector.py
    evaluate_pipeline.py
    list_obs_scenes.py
  src/pokemon_cv/
    app/
    capture/
    detect/
    embed/
    match/
    preprocess/
    smooth/
    utils/
  tests/
```

## Installation

1. Python 3.11+
2. Install dependencies:

```bash
pip install -r requirements.txt
```

Optional editable install:

```bash
pip install -e .
```

## OBS Setup (Primary Input)

1. In OBS, create/use your scene for sprite detection (example: `Sprite Detection`).
2. Start OBS WebSocket server:
   - OBS -> `Tools` -> `WebSocket Server Settings`
   - Enable server, note host/port/password (default host `127.0.0.1`, port `4455`).
3. Set that scene name in config (`camera.obs.scene_name`) or CLI (`--obs-scene`).

List scenes to verify exact names:

```bash
python scripts/list_obs_scenes.py --host 127.0.0.1 --port 4455
```

## Config Highlights

`configs/default.yaml` defaults to OBS scene input:

```yaml
camera:
  source: obs_scene
  obs:
    host: 127.0.0.1
    port: 4455
    password: ""
    scene_name: Sprite Detection
```

You can switch to webcam input:

```yaml
camera:
  source: webcam
  name: OBS Virtual Camera
```

## Reference Data Format

Reference images are loaded recursively.

Supported image extensions: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`.

Recommended structure:

```text
data/references/
  nincada/
    normal/
      0001.png
    shiny/
      0001.png
  taillow/
    normal/
      0001.png
```

Labeling logic:
- `species`: first folder under root
- `form`: intermediate folders except `normal/forms/sprites/shiny`
- `shiny`: true if folder or filename contains `shiny`
- `label`: `species[:form][:shiny]`

## Train Embedding Model

```bash
python scripts/train_embedding_model.py \
  --data-dir data/embedding_train \
  --output models/embedding/mobilenet_metric.pt \
  --epochs 25 \
  --batch-size 64 \
  --device cpu
```

Training augmentations mimic webcam/stream artifacts:
- blur
- noise
- JPEG compression
- gamma shift
- slight perspective warp
- scale variation
- partial occlusion

## Build FAISS Reference Index

```bash
python scripts/build_reference_index.py \
  --config configs/default.yaml \
  --references-dir data/references \
  --output-index artifacts/reference_index.faiss \
  --output-metadata artifacts/reference_metadata.json
```

## Detector Training (Optional)

```bash
python scripts/train_detector.py \
  --data-yaml data/detector/data.yaml \
  --model yolov8n.pt \
  --epochs 80 \
  --imgsz 640
```

## Runtime Commands

### Use OBS scene (recommended)

```bash
python -m pokemon_cv.app.cli \
  --config configs/default.yaml \
  --camera-source obs_scene \
  --obs-scene "Sprite Detection"
```

### Use OBS Virtual Camera as webcam fallback

```bash
python -m pokemon_cv.app.cli \
  --config configs/default.yaml \
  --camera-source webcam \
  --camera-name "OBS Virtual Camera" \
  --prefer-obs
```

Useful flags:
- `--mode roi|detector`
- `--no-display`
- `--no-json`
- `--max-frames N`
- `--debug-screen`
- `--fps`, `--width`, `--height`, `--frame-skip`

## Per-Frame JSON Output

Each frame event includes:
- `frame_id`
- `timestamp`
- `mode`
- `camera_source`
- `candidates` with top-k matches
- `frame_prediction` (raw)
- `stabilized_prediction` (N-of-M)

## Evaluation

```bash
python scripts/evaluate_pipeline.py \
  --config configs/default.yaml \
  --dataset-dir data/eval \
  --input-mode crop \
  --output-dir artifacts/eval
```

Outputs:
- `report.json` with:
  - top-1 accuracy
  - top-3 accuracy
  - unknown false-positive rate
  - latency ms/frame (mean/p95)
- `confusion_matrix.csv`

## Tests

```bash
pytest -q
```

## Troubleshooting

- OBS scene input fails:
  - Ensure OBS is running and WebSocket server is enabled.
  - Verify scene name with `scripts/list_obs_scenes.py`.
  - Confirm host/port/password in config.
- Too many false positives:
  - Increase `matching.margin_threshold`.
  - Increase `matching.similarity_threshold`.
  - Increase smoothing strictness (`min_votes`, `window_size`).
- Too many unknowns:
  - Lower `similarity_threshold` slightly.
  - Rebuild index and ensure embedding checkpoint matches domain.
- Screen not found:
  - Tune `screen.*` params and use `--debug-screen`.

## Extending to New Games/Layout

- Add/update ROIs for known layouts.
- Train detector and use `mode=detector` for unknown layouts.
- Add reference assets and rebuild FAISS index.
- Retrain embedding model for new visual domains.

## Assumptions

- Closed-set recognition with explicit unknown rejection.
- Shiny/form recognition depends on reference coverage quality.
- CPU throughput depends on detector mode, model size, and input resolution.