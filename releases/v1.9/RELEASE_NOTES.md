# PokeAchieve Tracker v1.9 Release Notes

## Version 1.9 - API Endpoint Updates 🚀

### What's New
- **Updated API Endpoints**: Now uses Codex-recommended `/api/` prefixed endpoints
- **New Auth Test**: `POST /api/tracker/test` for API key validation
- **New Collection Endpoints**:
  - `GET /api/collection` - Get tracker-style collection summary
  - `POST /api/collection/update` - Update single Pokemon entry
- **Improved Authentication**: Better API key auth flow with Bearer tokens

### Files Updated for v1.9
- `tracker_gui.py` - Version title and API endpoints
- `setup_directory_build.py` - Version bump
- `BUILD_DIRECTORY.bat` - Version bump
- `README.md` - Documentation updates

### Building the Release (Windows Required)

1. Clone/pull latest from GitHub:
   ```bash
   git clone https://github.com/ZakyPew/pokeachieve-tracker.git
   cd pokeachieve-tracker
   ```

2. Run the build script:
   ```
   BUILD_DIRECTORY.bat
   ```

3. The build will create `dist/PokeAchieveTracker/`

4. Create release zip:
   - Zip the `dist/PokeAchieveTracker/` folder
   - Name it: `PokeAchieveTracker-v1.9.zip`

5. Upload to GitHub Releases:
   - Go to https://github.com/ZakyPew/pokeachieve-tracker/releases
   - Create new release: v1.9
   - Attach `PokeAchieveTracker-v1.9.zip`

### Source Code
Source archive: `pokeachieve-tracker-v1.9-source.zip`

---
Built with love by Celest 💕
