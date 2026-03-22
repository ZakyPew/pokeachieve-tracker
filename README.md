# PokeAchieve Tracker 🎮

A Pokemon achievement tracker for RetroArch that automatically detects in-game progress and syncs with your PokeAchieve.com profile.

![Version](https://img.shields.io/badge/version-1.9-blue)
![Platform](https://img.shields.io/badge/platform-Windows-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Features ✨

- **Automatic Achievement Detection**: Tracks your progress in real-time while playing Pokemon games via RetroArch
- **Multiple Game Support**: Works with Pokemon Red, Blue, Yellow, Ruby, Sapphire, Emerald, FireRed, and LeafGreen
- **Sync with Server**: Download your collection from PokeAchieve.com directly in the app
- **Clear Data**: Reset your local tracker data anytime from the UI
- **Beautiful Overlay**: Stream-ready overlay showing your current progress
- **API Key Support**: Secure authentication with your PokeAchieve account

## What's New in v1.9 🎉

### API Endpoint Updates
- Updated to use Codex-recommended `/api/` prefixed endpoints
- New auth test endpoint: `POST /api/tracker/test`
- New collection endpoints: `GET /api/collection`, `POST /api/collection/update`
- Improved API key authentication flow

### Directory Build Mode
This release uses **directory mode** instead of a single-file executable:
- ✅ Faster startup times
- ✅ Easy to modify/add achievements
- ✅ Smaller main executable
- ✅ More reliable builds

### New Features
- **Clear Data Button**: Reset all tracker data from the UI
- **Sync with Server Button**: Fetch your collection from PokeAchieve.com
- **Improved Build System**: Uses cx_Freeze for better Windows compatibility

## Download 📥

Download the latest release from the [Releases page](../../releases).

1. Download `PokeAchieveTracker-v1.9.zip`
2. Extract to any folder
3. Run `PokeAchieveTracker.exe`
4. Log in with your PokeAchieve.com account

## Build from Source 🔧

Want to build it yourself? You'll need:

- Python 3.10 or newer
- Windows 10/11

### Quick Build

1. Clone the repository:
```bash
git clone https://github.com/ZakyPew/pokeachieve-tracker.git
cd pokeachieve-tracker
```

2. Run the build script:
```bash
BUILD_DIRECTORY.bat
```

3. Find your build in `dist/PokeAchieveTracker/`

### Manual Build

```bash
# Install dependencies
pip install -r requirements.txt

# Build the executable
python setup_directory_build.py build

# Output is in build/PokeAchieveTracker/
```

## Setup 🚀

1. **Install RetroArch** if you haven't already
2. **Enable Network Commands** in RetroArch:
   - Settings → Network → Network Command Enable → ON
3. **Run PokeAchieve Tracker**
4. **Log in** with your PokeAchieve.com account (or create one)
5. **Start playing** - achievements unlock automatically!

## Supported Games 🎮

| Game | Status |
|------|--------|
| Pokemon Red | ✅ Supported |
| Pokemon Blue | ✅ Supported |
| Pokemon Yellow | ✅ Supported |
| Pokemon Ruby | ✅ Supported |
| Pokemon Sapphire | ✅ Supported |
| Pokemon Emerald | ✅ Supported |
| Pokemon FireRed | ✅ Supported |
| Pokemon LeafGreen | ✅ Supported |

## File Structure 📁

```
PokeAchieveTracker/
├── PokeAchieveTracker.exe    # Main application
├── achievements/             # Achievement data files
│   ├── pokemon_red.json
│   ├── pokemon_blue.json
│   └── ...
├── python3.dll              # Python runtime
└── ...                      # Other dependencies
```

## API Integration 🔌

The tracker connects to PokeAchieve.com via REST API:
- Fetch your collection
- Unlock achievements
- Sync progress across devices

See [TRACKER_INTEGRATION.md](TRACKER_INTEGRATION.md) for API details.

## Troubleshooting 🔧

### "Python not found" error
Install Python 3.10+ from [python.org](https://python.org) and make sure to check "Add Python to PATH" during installation.

### "RetroArch not connected"
Make sure Network Commands are enabled in RetroArch settings.

### Achievements not unlocking
- Verify you're using a supported game
- Check that RetroArch is running the game
- Ensure the correct game is selected in the tracker

## Contributing 🤝

Contributions are welcome! Please feel free to submit a Pull Request.

## License 📄

MIT License - see LICENSE file for details.

## Credits 💕

Built with love by [Celest](https://github.com/celesta-ai) for PokeAchieve.com

---

**[Download Latest Release](../../releases/latest)** | **[Report Issues](../../issues)** | **[PokeAchieve.com](https://pokeachieve.com)**

## Per-Game AI Bootstrap (Battle Scenes + Training)

The tracker now includes scripts to bootstrap one model per supported game using internet battle scenes and your local sprite pack.

### 1) Download one battle scene per game

```bash
python scripts/download_battle_scenes.py --output-root assets/battle_scenes
```

### 2) Build synthetic datasets + train per-game ONNX models

```bash
python scripts/bootstrap_per_game_models.py --samples-per-species 50 --epochs 12 --device cpu
```

Outputs:
- Base scenes: `assets/battle_scenes/<game_slug>/base_scene.png`
- Synthetic datasets: `debug/ai_dataset/by_game/<game_slug>/labeled/`
- Models: `models/by_game/<game_slug>/tracker_species.onnx`
- Labels: `models/by_game/<game_slug>/tracker_species_labels.json`

Useful flags:
- `--games pokemon_emerald,pokemon_firered` to run a subset
- `--overwrite-datasets` to regenerate synthetic crops
- `--skip-train` to only prepare datasets
- `--skip-download` if scenes are already downloaded

## ONNX Verification Mode (OBS Sprite Feed)

Use this mode when you want to verify exactly what the ONNX model sees from the OBS source each frame.

1. Edit your config file: `C:\Users\thefo\.pokeachieve\config.json`
2. Add/update:

```json
{
  "video_ai_species_verification_mode": true,
  "video_ai_species_verify_log_interval_sec": 0.25,
  "video_ai_species_verify_topk_k": 3
}
```

3. Start the tracker and run encounters from your configured OBS source.

New log event:
- `video_ai_onnx_verify`
- Includes `onnx_topk` (top-k species with confidence and candidate flag), model source/game slug, and sprite ROI.

Encounter events now also include ONNX top-k fields:
- `onnx_topk_k`
- `onnx_candidate_count`
- `onnx_topk`

If you do not see `video_ai_onnx_verify` entries:
- Confirm ONNX Runtime is available (`onnxruntime_available=true` in preview log)
- Confirm a per-game model is present at `models/by_game/<game_slug>/tracker_species.onnx`
- Confirm `video_ai_species_enabled` is true.

## In-App Guided Training (No Scripts Needed)

You can now label and train directly from the tracker UI.

1. Start the tracker.
2. Click `Start Tracking`.
3. Click `Start Training Assist` (Status tab).
4. Run wild encounters in your OBS scene/source.
5. For each encounter, confirm the guess:
   - `Yes - Correct` if right
   - `No - Correct Label` if wrong, then select the right Pokemon
   - `Skip` to ignore
6. After collecting labels, click `Train Current Game Model`.
7. Test again in live encounters.

Notes:
- Labels are saved under `C:\Users\<you>\.pokeachieve\guided_training\<game_slug>\labeled\`.
- The trained model is written to `models/by_game/<game_slug>/tracker_species.onnx`.

## YOLO + ViT Pipeline (Custom Localizer)

If you want YOLO+ViT species recognition, use a custom YOLO localizer (`best.pt`) instead of COCO defaults (`yolov8n.pt`).

### 1) Train a single-class Pokemon localizer

```bash
python scripts/train_yolo_localizer.py --data path/to/data.yaml --epochs 100 --imgsz 640 --single-cls
```

Expected output weights:
- `runs/pokemon_localizer/train/weights/best.pt`

### 2) Point tracker to custom localizer

Edit `C:\Users\<you>\.pokeachieve\config.json`:

```json
{
  "video_species_engine": "yolo_vit",
  "video_yolo_vit_enabled": true,
  "video_yolo_model_path": "C:\\Users\\<you>\\...\\best.pt",
  "video_yolo_vit_localizer_enabled": true,
  "video_yolo_vit_allow_coco_localizer": false,
  "video_yolo_vit_min_confidence": 0.40,
  "video_yolo_vit_min_margin": 0.08
}
```

### 3) Optional async webcam smoke test

```bash
python scripts/run_pokemon_yolo_vit_async_demo.py --yolo C:\\path\\to\\best.pt
```

Notes:
- The tracker now guards against accidental COCO localizer usage unless `video_yolo_vit_allow_coco_localizer=true`.
- The async demo clamps boxes to frame bounds and applies softmax confidence thresholding.
