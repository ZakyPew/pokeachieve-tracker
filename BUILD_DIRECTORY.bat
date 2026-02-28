@echo off
REM Build PokeAchieve Tracker v1.8.5 - DIRECTORY MODE

echo ==========================================
echo PokeAchieve Tracker v1.8.5 - Directory Build
echo ==========================================
echo.

REM Try to find Python
set PYTHON_CMD=C:\Users\ZakHa\AppData\Local\Python\bin\python.exe

if exist "%PYTHON_CMD%" (
    echo Found Python: %PYTHON_CMD%
    goto :found_python
)

python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    echo Found Python in PATH
    goto :found_python
)

echo ERROR: Python not found at C:\Users\ZakHa\AppData\Local\Python\bin\python.exe
echo Please install Python or update this script with your Python path.
pause
exit /b 1

:found_python
%PYTHON_CMD% --version
echo.

REM Install dependencies
echo Installing dependencies...
%PYTHON_CMD% -m pip install cx_Freeze requests psutil pywin32 pillow tkinter-tooltip -q

REM Clean previous builds
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Ensure achievements folder exists
echo Setting up achievements folder...
if not exist achievements mkdir achievements

REM Build
echo.
echo Building... (this may take 2-3 minutes)
echo.
%PYTHON_CMD% setup_directory_build.py build

if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    pause
    exit /b 1
)

REM Copy to dist
echo.
echo Creating dist folder...
mkdir dist 2>nul
xcopy /E /I /Y "build\PokeAchieveTracker" "dist\PokeAchieveTracker"

echo.
echo ==========================================
echo BUILD SUCCESS! 
echo ==========================================
echo Output: dist\PokeAchieveTracker\
echo.
pause
