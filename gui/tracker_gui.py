"""Compatibility wrapper for legacy import paths.

This module intentionally delegates to the canonical top-level `tracker_gui.py`
to reduce merge conflicts with older branches that still reference `gui/tracker_gui.py`.
"""

from tracker_gui import *  # noqa: F401,F403

if __name__ == "__main__":
    from tracker_gui import main

    main()
