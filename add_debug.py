# Add debug logging to game detection
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Add more debug output to get_current_game
old_get_game = '''    def get_current_game(self) -> Optional[str]:
        """Get name of currently loaded game from GET_STATUS"""
        response = self.send_command("GET_STATUS")
        if response and response.startswith("GET_STATUS"):
            # Parse: GET_STATUS PAUSED game_boy,Pokemon Red(Enhanced),crc32=...
            try:
                parts = response.replace("GET_STATUS ", "").split(",")
                if len(parts) >= 2:
                    return parts[1].strip()  # Pokemon name is 2nd part
            except:
                pass
        return None'''

new_get_game = '''    def get_current_game(self) -> Optional[str]:
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

content = content.replace(old_get_game, new_get_game)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Added debug logging to get_current_game!')
