# PokeAchieve Tracker 🎮

A Pokemon achievement tracker for RetroArch that automatically detects in-game progress and syncs with your PokeAchieve.com profile.

![Version](https://img.shields.io/badge/version-1.8.2-blue)
![Platform](https://img.shields.io/badge/platform-Windows-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Features ✨

- **Automatic Achievement Detection**: Tracks your progress in real-time while playing Pokemon games via RetroArch
- **Multiple Game Support**: Works with Pokemon Red, Blue, Yellow, Ruby, Sapphire, Emerald, FireRed, and LeafGreen
- **Sync with Server**: Download your collection from PokeAchieve.com directly in the app
- **Clear Data**: Reset your local tracker data anytime from the UI
- **Beautiful Overlay**: Stream-ready overlay showing your current progress
- **API Key Support**: Secure authentication with your PokeAchieve account

## What's New in v1.8.3 🎉

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

1. Download `PokeAchieveTracker-v1.8.3.zip`
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
