# Build PokeAchieve Tracker v1.6

## Prerequisites
- Python 3.11+ installed
- pip install pyinstaller requests

## Build Steps

### Option 1: Simple Build (Recommended)
```powershell
cd C:\PokeAchieve\tracker\gui

# Use your Python's pyinstaller
C:\Users\ZakHa\AppData\Local\Python\pythoncore-3.14-64\Scripts\pyinstaller.exe `
  --windowed `
  --name "PokeAchieveTracker_v1.6" `
  --add-data "../achievements;achievements" `
  tracker_gui.py
```

### Option 2: Build with Console (for debugging)
```powershell
cd C:\PokeAchieve\tracker\gui
C:\Users\ZakHa\AppData\Local\Python\pythoncore-3.14-64\Scripts\pyinstaller.exe `
  --name "PokeAchieveTracker_v1.6" `
  --add-data "../achievements;achievements" `
  tracker_gui.py
```

## After Build

The output will be in:
```
dist\PokeAchieveTracker_v1.6\
├── PokeAchieveTracker_v1.6.exe
└── achievements\
    └── games\
        ├── pokemon_red.json
        ├── pokemon_blue.json
        └── ... (all 10 games)
```

## Run

1. Navigate to `dist\PokeAchieveTracker_v1.6\`
2. Double-click `PokeAchieveTracker_v1.6.exe`
3. Enter API key from https://pokeachieve.com/dashboard.html
4. Start RetroArch with Pokemon game
5. Click "Connect" then "Start Tracking"

## What's New in v1.6

- Track ALL caught Pokemon from Pokedex (party + PC storage)
- Records catch dates for collection page
- Game detection for RetroArch format ("Pokemon - Red Version")
- API key authentication
- 361 achievements across 10 games
- Story achievements (HM detection, etc.)

## Troubleshooting

**"pyinstaller not found"**
- Use full path: `C:\Users\ZakHa\AppData\Local\Python\pythoncore-3.14-64\Scripts\pyinstaller.exe`

**"achievements not found"**
- Make sure achievements folder is copied to dist folder after build
- Run EXE from inside `dist\PokeAchieveTracker_v1.6\` folder

**Game not detected**
- Ensure RetroArch Settings → Network → Enable Network Command (port 55355)
- Load game before clicking Connect
