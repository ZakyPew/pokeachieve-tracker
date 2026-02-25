# PROJECT_MEM.md - PokeAchieve Tracker

**Project:** PokeAchieve Tracker  
**Location:** `~/projects/active/pokeachieve/tracker/`  
**Created:** 2026-02-20  
**Last Updated:** 2026-02-24  

## 🎯 Current Goal
Cross-platform GUI tracker that connects to RetroArch, tracks Pokemon achievements, and syncs with PokeAchieve platform.

## ✅ Completed
- [x] RetroArch TCP client (port 55355)
- [x] Memory reading via `READ_CORE_MEMORY`
- [x] Achievement condition evaluation (>, <, ==, !=, &)
- [x] Cross-platform Tkinter GUI (Windows/Linux/macOS)
- [x] Auto game detection from ROM name
- [x] Auto RetroArch connection with status indicator
- [x] Real-time achievement polling (configurable interval)
- [x] Progress persistence (~/.pokeachieve/progress.json)
- [x] Recent unlocks tab with timestamps
- [x] All achievements tab with unlock status
- [x] Log tab for debugging
- [x] Settings dialog for host/port/polling
- [x] **PokeAchieve API integration**
- [x] **API key authentication**
- [x] **Automatic sync on startup**
- [x] **Real-time unlock posting to platform**
- [x] **Dual status indicators (RetroArch + API)**
- [x] **FIXED: API endpoint paths (2026-02-24)**
- [x] **FIXED: Backend route configuration (2026-02-24)**
- [x] **ADDED: Enhanced API logging for debugging (2026-02-24)**

## 🔄 In Progress
- [ ] Testing with actual RetroArch + Pokemon ROMs
- [ ] Achievement unlock notifications (overlay?)
- [ ] Background retry queue for offline support

## 📝 Key Decisions
- **GUI Framework:** Tkinter (built into Python, zero dependencies)
- **Architecture:** Background polling thread + main GUI thread
- **Persistence:** JSON file in user's home directory
- **Communication:** Thread-safe queue for unlock events

## 🔧 Technical Notes

### Files
- `gui/tracker_gui.py` - Main application (~550 lines)
- `gui/__init__.py` - Package init
- `gui/README.md` - Usage documentation
- `run_tracker.py` - Launcher script
- `achievements/games/*.json` - Achievement definitions

### How to Run
```bash
cd ~/projects/active/pokeachieve/tracker
python3 run_tracker.py
```

### RetroArch Setup Required
1. Settings → Network → Enable Network Command
2. Port: 55355 (default)
3. Restart RetroArch

### Memory Reading
Uses RetroArch's `READ_CORE_MEMORY address length` command:
```
READ_CORE_MEMORY 0xD16B 1
→ READ_CORE_MEMORY 0xD16B 1 FF
```

## 🐛 Known Issues
- GUI might flicker on some Linux setups (Tkinter limitation)
- Achievement icons not yet implemented (using rarity colors instead)

## 🔧 Critical Fix - 2026-02-24

### Problem: API Communication Failure
The tracker was not syncing achievements to the backend API due to mismatched endpoint paths.

### Root Cause
Nginx proxy strips `/api/` prefix when forwarding to backend:
- Request: `POST /api/tracker/unlock`
- Nginx forwards: `POST /tracker/unlock` to backend
- Backend expected: `POST /api/tracker/unlock`
- Result: 404 Not Found

### Solution
Updated both backend routes and tracker client to use paths without `/api` prefix:
- Backend: `@app.post("/tracker/unlock")`
- Tracker: `self._request("POST", "/tracker/unlock")`
- Nginx: Proxies `/api/tracker/unlock` → `/tracker/unlock` ✓

### Files Changed
1. `/home/pokeachieve/pokeachieve-platform/backend/main.py` - Fixed route paths
2. `/home/zak/projects/active/pokeachieve/tracker/gui/tracker_gui.py` - Fixed API client paths

### Status
✅ **FIXED** - API communication now working correctly.

## 💡 Ideas / Backlog
- [ ] Systray/minimize to tray
- [ ] Desktop notifications for unlocks
- [ ] Achievement sound effects
- [ ] Export progress to platform API
- [ ] Support for more Pokemon games (Gen 4-9)
