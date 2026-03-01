# Changelog for PokeAchieve Tracker and Site Fixes - 2026-03-01

## Backup
- Tar backup of /home/pokeachieve/ created on VPS as /root/pokeachieve_backup_20260301.tar.gz
- DB dump failed (mysqldump connection error - can't connect to socket) - will attempt to fix manually if needed

## Tracker Changes
- 

## Site Changes
- 

## Deployment Notes
- 

All changes committed with messages referencing this changelog.

 - Fixed game name parsing in tracker_gui.py to strip \"Playing\" and locales (e.g., (USA, Europe)) and normalize version names.
 - Updated collection sync to send \"game_id\" instead of \"game\" string in batch update.
