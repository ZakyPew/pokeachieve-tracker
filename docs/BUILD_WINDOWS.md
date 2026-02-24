# Building PokeAchieve Tracker for Windows

## Prerequisites (on Windows)

1. **Install Python 3.10+** from python.org
2. **Install PyInstaller:**
   ```cmd
   pip install pyinstaller
   ```

## Build Steps

### 1. Copy Tracker Files to Windows

Copy this entire folder to your Windows machine:
```
~/projects/active/pokeachieve/tracker/  →  C:\PokeAchieve\tracker\
```

### 2. Create Build Script

Create `build_windows.bat` in the tracker folder:

```bat
@echo off
echo Building PokeAchieve Tracker for Windows...

pyinstaller ^
    --name "PokeAchieveTracker" ^
    --onefile ^
    --windowed ^
    --icon=assets/icon.ico ^
    --add-data "achievements;achievements" ^
    --add-data "integrations;integrations" ^
    --hidden-import=tkinter ^
    --hidden-import=socket ^
    --hidden-import=json ^
    --hidden-import=urllib.request ^
    run_tracker.py

echo Build complete!
echo Executable: dist\PokeAchieveTracker.exe
pause
```

### 3. Run Build

Open Command Prompt in the tracker folder:
```cmd
cd C:\PokeAchieve\tracker
build_windows.bat
```

### 4. Output

The .exe will be created at:
```
dist\PokeAchieveTracker.exe
```

## Alternative: Simple Build (No Icon/Assets)

If you just want a quick .exe:

```cmd
cd C:\PokeAchieve\tracker
pyinstaller --onefile --windowed run_tracker.py
```

Output: `dist\run_tracker.exe`

## Testing the Windows Build

1. Double-click `PokeAchieveTracker.exe`
2. Should open GUI window
3. Enter your API key from PokeAchieve dashboard
4. Click "Connect to RetroArch"
5. Start a Pokemon game in RetroArch
6. Watch achievements unlock!

## Distribution

To share with others:
- Zip the `dist\PokeAchieveTracker.exe` file
- Or use an installer like Inno Setup for professional look

## Troubleshooting

**"Failed to execute script" error:**
- Make sure all Python files are in the same folder
- Try without `--onefile` flag for debugging

**Missing tkinter:**
- Reinstall Python with "tcl/tk and IDLE" checked

**Antivirus blocks .exe:**
- Add exception or sign the executable (advanced)
