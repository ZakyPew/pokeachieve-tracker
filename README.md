# PokeAchieve Tracker v1.7

Cross-platform GUI application that connects RetroArch to the PokeAchieve platform for real-time achievement and Pokemon collection tracking.

![Version](https://img.shields.io/badge/version-1.7-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-green)
![License](https://img.shields.io/badge/license-Private-red)

## 🎮 Features

- **Achievement Tracking** - Automatically unlock achievements as you play
- **Pokedex Sync** - Real-time collection progress to PokeAchieve platform
- **Multi-Game Support** - Works with Pokemon games from Gen 1-3
- **RetroArch Integration** - Reads memory directly from emulator
- **Cross-Platform** - Windows and Linux support

## 📋 Supported Games

### Generation 1
- ✅ Pokemon Red
- ✅ Pokemon Blue

### Generation 2
- ✅ Pokemon Gold
- ✅ Pokemon Silver
- ✅ Pokemon Crystal

### Generation 3 (RSE)
- ✅ Pokemon Ruby
- ✅ Pokemon Sapphire
- ✅ Pokemon Emerald

### Generation 3 (FRLG)
- ✅ Pokemon FireRed
- ✅ Pokemon LeafGreen

## 🚀 Quick Start

### Windows Users (Pre-built)
1. Download `PokeAchieve-Tracker-v1.7-windows.zip` from [Releases](https://github.com/ZakyPew/pokeachieve-tracker/releases)
2. **IMPORTANT**: The ZIP contains both the .exe AND the `achievements/` folder
3. Extract the entire ZIP to a folder
4. **Keep the .exe and achievements/ folder together!**
5. Double-click `PokeAchieve-Tracker-v1.7.exe`
6. Enter your API key from PokeAchieve dashboard
7. Select your game and click "Connect to RetroArch"

### Folder Structure (IMPORTANT!)
```
YourFolder/
├── PokeAchieve-Tracker-v1.7.exe
├── README.txt
└── achievements/
    └── games/
        ├── pokemon_red.json
        ├── pokemon_blue.json
        ├── pokemon_ruby.json
        └── ... (10 game files total)
```

⚠️ **The achievements/ folder must be in the same folder as the .exe!**

### Requirements
- Windows 10/11 or Linux
- [RetroArch](https://www.retroarch.com/) with network commands enabled
- PokeAchieve platform account
- API key from your PokeAchieve dashboard

## 🆕 What's New in v1.7

### Fixed
- **Separate RSE vs FRLG Memory Configs**
  - Ruby/Sapphire/Emerald now use correct Hoenn addresses (`0x0202985C`)
  - FireRed/LeafGreen now use correct Kanto addresses (`0x02024E04`)
  - Fixes false positives at game start
  - Proper dex sizes: 202 for Hoenn, 151 for Kanto

### Previous Versions
- v1.6 - Added Gen 3 support
- v1.5 - UI improvements
- v1.4 - Initial Windows release

## 🛠️ Building from Source

### Prerequisites
- Python 3.8 or higher
- pip

### Windows Build
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PokeAchieve-Tracker-v1.7" tracker_gui.py
```

**After building**: Copy the `achievements/` folder next to the .exe in the `dist/` folder!

### Linux Build
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PokeAchieve-Tracker" tracker_gui.py
```

### Project Structure

```
pokeachieve-tracker/
├── tracker_gui.py          # Main application
├── game_configs.py         # Memory configurations per game
├── achievements/           # Achievement definitions (REQUIRED!)
│   └── games/
│       ├── pokemon_red.json
│       ├── pokemon_blue.json
│       └── ...
├── gui/                    # GUI assets
├── TRACKER_INTEGRATION.md  # API documentation
└── README.md              # This file
```

## 🔧 Configuration

### RetroArch Setup
1. Open RetroArch
2. Settings → Network → Network Command
3. Enable "Network Command"
4. Set port to `55355` (default)

### Game Memory
The tracker uses game-specific memory addresses defined in `game_configs.py`:
- Gen 1: Classic GB addresses
- Gen 2: GBC-specific addresses
- Gen 3 RSE: GBA Hoenn addresses
- Gen 3 FRLG: GBA Kanto addresses

## ⚠️ Troubleshooting

**"Achievement file not found" error**
- Make sure the `achievements/games/` folder is next to the .exe
- Don't move the .exe without the achievements folder

**"Cannot connect to RetroArch"**
- Make sure RetroArch is running
- Check that Network Command is enabled in RetroArch settings
- Verify port 55355 is not blocked

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/ZakyPew/pokeachieve-tracker/issues)
- **Platform**: [PokeAchieve Dashboard](https://pokeachieve.com)

## 📝 License

Private - PokeAchieve Platform

---

**Built with ❤️ for the PokeAchieve community**
