#!/usr/bin/env python3
"""
PokeAchieve Tracker Launcher
Cross-platform launcher script - works on Windows, Linux, and macOS
"""

import sys
import os

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from gui.tracker_gui import main

if __name__ == "__main__":
    main()
