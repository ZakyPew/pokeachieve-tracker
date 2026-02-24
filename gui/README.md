# PokeAchieve Tracker

Cross-platform GUI achievement tracker for Pokemon games via RetroArch. Syncs with PokeAchieve platform.

## Features

- 🔌 Auto-detects RetroArch connection (port 55355)
- 🎮 Auto-detects loaded Pokemon ROM
- 🏆 Real-time achievement tracking
- 📊 Progress bar and stats
- 💾 Persistent unlock state
- 🌐 **Syncs with PokeAchieve platform** (NEW!)
- 🔑 **API key authentication** (NEW!)
- 🖥️ Works on Windows, Linux, and macOS

## Setup

### 1. Enable RetroArch Network Commands

In RetroArch:
1. Go to `Settings → Network`
2. Enable `Network Command`
3. Set port to `55355` (default)
4. Restart RetroArch

### 2. Get API Key from PokeAchieve

1. Log in to your PokeAchieve account
2. Go to Settings → API Keys
3. Click "Generate New Key"
4. Copy the key (shown only once!)

### 3. Configure Tracker

1. Run the tracker
2. Click `⚙ Settings`
3. Enter:
   - **Platform URL**: `http://localhost:8000` (local) or your production URL
   - **API Key**: Paste your key from step 2
4. Click `Test Connection` to verify
5. Check `Sync achievements to platform`
6. Click `Save`

### 4. Run the Tracker

**Windows:**
```bash
python run_tracker.py
```

**Linux/macOS:**
```bash
python3 run_tracker.py
```

## How It Works

1. Start RetroArch and load a Pokemon ROM
2. Run the tracker
3. Tracker auto-connects to RetroArch
4. Tracker detects which game is loaded
5. **Syncs progress from PokeAchieve platform** (if API key configured)
6. Starts polling memory for achievement conditions
7. **Posts unlocks to PokeAchieve platform in real-time**
8. Shows unlock notifications locally

## GUI Tabs

- **🏆 Recent Unlocks** - Shows recently unlocked achievements with timestamps
- **📋 All Achievements** - Complete list with lock/unlock status
- **📝 Log** - Connection events, API sync status, debug info

## Supported Games

| Game | Platform | Game ID |
|------|----------|---------|
| Pokemon Red | GB | 1 |
| Pokemon Blue | GB | 2 |
| Pokemon Emerald | GBA | 3 |
| Pokemon FireRed | GBA | 4 |
| Pokemon LeafGreen | GBA | 5 |

## Settings

Click `⚙ Settings` to configure:

### PokeAchieve API
- **Platform URL** - Your PokeAchieve instance URL
- **API Key** - Your personal API key
- **Sync achievements** - Enable/disable cloud sync

### RetroArch
- **Host** - RetroArch address (default: 127.0.0.1)
- **Port** - RetroArch command port (default: 55355)

### Tracking
- **Poll Interval** - How often to check memory (default: 500ms)

## Data Storage

### Local Progress
- **Windows:** `%USERPROFILE%\.pokeachieve\progress.json`
- **Linux/macOS:** `~/.pokeachieve/progress.json`

### Configuration
- **Windows:** `%USERPROFILE%\.pokeachieve\config.json`
- **Linux/macOS:** `~/.pokeachieve/config.json`

## Troubleshooting

### "Not Connected" Status (RetroArch)
- Make sure RetroArch is running
- Check that Network Command is enabled in RetroArch settings
- Verify port 55355 is not blocked by firewall
- Try clicking `🔌 Reconnect`

### "API Authentication Failed"
- Verify your API key is correct
- Check that the Platform URL is correct
- Ensure you have internet connectivity
- Try clicking `Test Connection` in Settings

### Game Not Detected
- Make sure a Pokemon ROM is loaded in RetroArch
- Check that the ROM name matches known titles
- Look at the Log tab for debug info

### Achievements Not Unlocking
- Verify the memory addresses in the achievement JSON files
- Check the Log tab for read errors
- Ensure you're using the correct ROM version

### Sync Issues
- Click `🔄 Sync Now` to manually trigger sync
- Check Log tab for API error messages
- Verify `Sync achievements to platform` is enabled in Settings

## API Endpoints Used

The tracker communicates with PokeAchieve via these endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tracker/test` | POST | Verify API key |
| `/api/tracker/progress/{game_id}` | GET | Get progress for sync |
| `/api/tracker/unlock` | POST | Report achievement unlock |

## Security Notes

- API keys are stored locally in `config.json`
- API keys are hashed before storage on the server
- Only the platform can validate keys (not reversible)
- Use HTTPS in production for encrypted communication

## Development

The tracker consists of:
- `gui/tracker_gui.py` - Main GUI application (~800 lines)
- `gui/__init__.py` - Package init
- `run_tracker.py` - Launcher script
- `achievements/games/*.json` - Achievement definitions

### Key Classes

- `PokeAchieveAPI` - HTTP client for platform API
- `RetroArchClient` - TCP client for RetroArch
- `AchievementTracker` - Core tracking logic
- `PokeAchieveGUI` - Tkinter interface

## License

MIT License - See LICENSE file
