"""
Build script for PokeAchieve Tracker - DIRECTORY MODE
"""

import sys
import os
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": [
        "tkinter", "socket", "json", "time", "threading", 
        "queue", "os", "pathlib", "typing", 
        "datetime", "dataclasses", "requests", "psutil",
        "ssl", "urllib", "http", "email", "encodings", "certifi"
    ],
    "excludes": ["numpy", "pandas", "matplotlib", "test", "pydoc"],
    "include_files": [
        ("achievements", "achievements"),
    ],
    "optimize": 2,
    "build_exe": "build/PokeAchieveTracker",
}

base = "gui" if sys.platform == "win32" else None

executables = [
    Executable(
        "tracker_gui.py",
        base=base,
        target_name="PokeAchieveTracker.exe",
        icon=None,
    )
]

if not os.path.exists("achievements"):
    os.makedirs("achievements")

setup(
    name="PokeAchieve Tracker",
    version="1.8.4",
    description="Pokemon Achievement Tracker for RetroArch - Directory Mode",
    author="PokeAchieve",
    options={"build_exe": build_exe_options},
    executables=executables,
)

print("\nBuild Complete!")
print("Output: build/PokeAchieveTracker/")
