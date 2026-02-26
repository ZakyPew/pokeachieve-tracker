@echo off
echo Building PokeAchieve Tracker v1.4...
cd /d "%~dp0"
cd gui

:: Install requirements if needed
pip install pyinstaller requests

:: Build the exe
pyinstaller --onefile --windowed --name "PokeAchieveTracker_v1.4" --add-data "../achievements;achievements" tracker_gui.py

echo Build complete! Check gui/dist/PokeAchieveTracker_v1.4.exe
pause
