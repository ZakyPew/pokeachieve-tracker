# Add more debug output to game loading and fix matching
with open('tracker_gui.py', 'r') as f:
    content = f.read()

old_load = '''    def _load_game_achievements(self, game_name: str):
        """Load achievements for detected game"""
        # Strip ROM hack suffixes like "(Enhanced)" for matching
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        game_map = {'''

new_load = '''    def _load_game_achievements(self, game_name: str):
        """Load achievements for detected game"""
        # Strip ROM hack suffixes like "(Enhanced)" for matching
        clean_name = re.sub(r'\([^)]*\)', '', game_name).strip()
        print(f"[DEBUG] Loading achievements for: {game_name}")
        print(f"[DEBUG] Cleaned name: {clean_name}")
        print(f"[DEBUG] Achievements dir: {self.achievements_dir}")
        print(f"[DEBUG] Achievements dir exists: {self.achievements_dir.exists()}")
        game_map = {'''

content = content.replace(old_load, new_load)

# Also add debug after the matching loop
old_match = '''        if achievement_file and achievement_file.exists():'''
new_match = '''        print(f"[DEBUG] Looking for match in: {clean_name.lower()}")
        for key, filename in game_map.items():
            print(f"[DEBUG] Checking if '{key.lower()}' in '{clean_name.lower()}'")
        print(f"[DEBUG] Achievement file: {achievement_file}")
        print(f"[DEBUG] Achievement file exists: {achievement_file.exists() if achievement_file else False}")
        if achievement_file and achievement_file.exists():'''

content = content.replace(old_match, new_match)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Added debug output to game loading!')
