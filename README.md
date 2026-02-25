# PokeAchieve Tracker 🎮

**Desktop Achievement Tracker for Pokemon Games**

Sync your Pokemon gameplay with PokeAchieve and unlock achievements automatically!

## 📥 Download

Download the latest release from [GitHub Releases](../../releases)

**File:** `PokeAchieveTracker-v1.1.zip`

Extract and run `run_tracker.exe`

---

## 🚀 Quick Start Guide

### 1. Get Your API Key

1. Go to [pokeachieve.com/dashboard.html](https://pokeachieve.com/dashboard.html)
2. Log in to your account
3. Scroll to **"API Keys"** section
4. Enter a name (e.g., "Desktop Tracker")
5. Click **"Generate Key"**
6. **COPY THE KEY IMMEDIATELY** (you won't see it again!)

### 2. Setup RetroArch

1. **Start RetroArch**
2. Load a Pokemon game (Red, Blue, Emerald, FireRed, or LeafGreen)
3. Go to **Settings → Network**
4. Enable:
   - ✅ **Network Command** = ON
   - ✅ **Network Command Port** = 55355
   - ✅ **STDIN Command** = ON
5. **Restart RetroArch** with the game loaded

### 3. Configure the Tracker

1. **Open** `run_tracker.exe`
2. Click **"Settings"** (gear icon)
3. **Platform URL:** `https://pokeachieve.com` (already set)
4. **API Key:** Paste your key from step 1
5. Click **"Save"**
6. Click **"Test Connection"**
   - Should show: **"API: Connected ✓"**

### 4. Connect to RetroArch

1. Make sure RetroArch is running with a Pokemon game
2. In the tracker, click **"Connect to RetroArch"**
   - Should show: **"RetroArch: Connected ✓"**
   - Should detect: **"Game: Pokemon [Version]"**

### 5. Start Tracking!

1. Click **"Start Tracking"**
2. Play the game normally!
3. Achievements unlock automatically and sync to the website

---

## 🎮 Supported Games

| Game | Platform | Achievements |
|------|----------|--------------|
| Pokemon Red | Game Boy | 50+ |
| Pokemon Blue | Game Boy | 50+ |
| Pokemon Emerald | GBA | 40+ |
| Pokemon FireRed | GBA | 50+ |
| Pokemon LeafGreen | GBA | 50+ |

---

## 🔧 Troubleshooting

### "API Connection Failed"
- Make sure you copied the **entire** API key
- Check your internet connection
- Verify the Platform URL is `https://pokeachieve.com`

### "RetroArch Disconnected"
- Make sure a **game is loaded** (not just the menu)
- Check that Network Command is **enabled**
- Try restarting RetroArch after enabling Network Command
- Check Windows Firewall isn't blocking port 55355

### "No Game Detected"
- Load a Pokemon ROM in RetroArch first
- Only Pokemon Red/Blue/Emerald/FireRed/LeafGreen are supported

### Achievements Not Unlocking
- Make sure tracking is started (green status)
- Some achievements require specific actions (check description)
- Try unpausing the game in RetroArch

---

## 📝 How Achievements Work

The tracker reads your game's memory in real-time:

- **Story Achievements** — Detected when you reach certain points
- **Collection Achievements** — Track Pokemon caught
- **Gym Badges** — Detected when you earn badges
- **Completion Achievements** — Pokedex completion, etc.

All progress syncs instantly to your PokeAchieve profile!

---

## 🔒 Privacy & Security

- Your API key is stored locally on your PC
- Only achievement data is sent to PokeAchieve
- No personal game data is uploaded
- We never see your ROM files or saves

---

## 🤝 Contributing

Want to add achievements for more Pokemon games?

1. Edit the JSON files in `achievements/games/`
2. Follow the existing format
3. Submit a Pull Request

---

## 📜 License

MIT License - See [LICENSE](LICENSE)

Pokemon is a trademark of Nintendo. This project is not affiliated with Nintendo.

---

Made with ❤️ for the Pokemon achievement hunting community
