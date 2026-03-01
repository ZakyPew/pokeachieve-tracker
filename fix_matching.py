# Fix game matching to handle "Version Playing" and dashes
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Fix the matching logic - just check if key words match
old_matching = '''        achievement_file = None
        display_name = None
        for key, filename in game_map.items():
            if key.lower() in clean_name.lower():
                achievement_file = self.achievements_dir / filename
                display_name = key
                break'''

new_matching = '''        achievement_file = None
        display_name = None
        clean_lower = clean_name.lower()
        print(f"[DEBUG] Cleaned name (lower): {clean_lower}")
        for key, filename in game_map.items():
            key_lower = key.lower()
            print(f"[DEBUG] Checking if '{key_lower}' in '{clean_lower}'")
            # Check if key is in cleaned name (handles "pokemon emerald" in "pokemon - emerald version playing")
            if key_lower in clean_lower:
                achievement_file = self.achievements_dir / filename
                display_name = key
                print(f"[DEBUG] MATCH FOUND: {key} -> {filename}")
                break
            # Also try matching individual words (e.g., "emerald" matches)
            key_words = key_lower.replace("pokemon ", "")
            if key_words in clean_lower:
                achievement_file = self.achievements_dir / filename
                display_name = key
                print(f"[DEBUG] MATCH FOUND (word match): {key} -> {filename}")
                break'''

content = content.replace(old_matching, new_matching)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Fixed game matching logic!')
