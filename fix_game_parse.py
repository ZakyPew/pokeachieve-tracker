# Fix game name parsing to handle commas in game names
with open('tracker_gui.py', 'r') as f:
    content = f.read()

old_parse = '''    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        print(f"[DEBUG] RetroArch GET_STATUS response: {response}")
        if response and response.startswith("GET_STATUS"):
            # Parse: GET_STATUS PAUSED game_boy,Pokemon Red(Enhanced),crc32=...
            try:
                parts = response.replace("GET_STATUS ", "").split(",")
                print(f"[DEBUG] Parsed parts: {parts}")
                if len(parts) >= 2:
                    game_name = parts[1].strip()
                    print(f"[DEBUG] Detected game: {game_name}")
                    return game_name
            except Exception as e:
                print(f"[DEBUG] Error parsing game name: {e}")
                pass
        return None'''

new_parse = '''    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        print(f"[DEBUG] RetroArch GET_STATUS response: {response}")
        if response and response.startswith("GET_STATUS"):
            # Parse: GET_STATUS PAUSED game_boy,Pokemon Red(Enhanced),crc32=...
            # Handle game names with commas like "Pokemon - Emerald Version (USA, Europe)"
            try:
                # Remove GET_STATUS prefix
                rest = response.replace("GET_STATUS ", "")
                # Split by crc32= to get the part before it
                if ",crc32=" in rest:
                    before_crc = rest.split(",crc32=")[0]
                else:
                    before_crc = rest
                # Now split by first comma to get platform and game name
                if "," in before_crc:
                    platform, game_name = before_crc.split(",", 1)
                    game_name = game_name.strip()
                    print(f"[DEBUG] Detected game: {game_name}")
                    return game_name
            except Exception as e:
                print(f"[DEBUG] Error parsing game name: {e}")
                pass
        return None'''

content = content.replace(old_parse, new_parse)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Fixed game name parsing to handle commas!')
