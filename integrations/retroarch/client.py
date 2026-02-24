# RetroArch Integration Module
# Connects to RetroArch via network command interface for real-time achievement tracking

import socket
import json
import time
import threading
from typing import Callable, Optional, Dict, List

class RetroArchClient:
    """Client for connecting to RetroArch network command interface"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 55355):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        self.callbacks: List[Callable] = []
        self.poll_thread: Optional[threading.Thread] = None
    
    def connect(self) -> bool:
        """Connect to RetroArch"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(5)
            self.socket.connect((self.host, self.port))
            self.connected = True
            print(f"Connected to RetroArch at {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"Failed to connect to RetroArch: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from RetroArch"""
        self.running = False
        self.connected = False
        if self.socket:
            self.socket.close()
            self.socket = None
    
    def send_command(self, command: str) -> Optional[str]:
        """Send a command to RetroArch and get response"""
        if not self.connected or not self.socket:
            return None
        
        try:
            self.socket.send(f"{command}\n".encode())
            response = self.socket.recv(4096).decode().strip()
            return response
        except Exception as e:
            print(f"Command failed: {e}")
            self.connected = False
            return None
    
    def get_current_game(self) -> Optional[Dict]:
        """Get information about currently loaded game"""
        response = self.send_command("GET_CURRENT_GAME")
        if response:
            try:
                return json.loads(response)
            except:
                return {"raw": response}
        return None
    
    def read_memory(self, address: str, num_bytes: int = 1) -> Optional[int]:
        """Read memory from the emulator"""
        # Format: READ_CORE_MEMORY address length
        response = self.send_command(f"READ_CORE_MEMORY {address} {num_bytes}")
        if response and response.startswith("READ_CORE_MEMORY"):
            parts = response.split()
            if len(parts) >= 3:
                # Parse hex values
                try:
                    values = [int(x, 16) for x in parts[2:]]
                    if len(values) == 1:
                        return values[0]
                    return values
                except ValueError:
                    pass
        return None
    
    def get_status(self) -> Dict:
        """Get RetroArch status"""
        response = self.send_command("GET_STATUS")
        if response:
            # Parse status: "PLAYING game_name,core_name,..." or "PAUSED" or "CONTENTLESS"
            parts = response.split(",")
            return {
                "raw": response,
                "status": parts[0] if parts else "UNKNOWN"
            }
        return {"status": "DISCONNECTED"}
    
    def add_callback(self, callback: Callable):
        """Add a callback for memory polling"""
        self.callbacks.append(callback)
    
    def start_polling(self, interval: float = 1.0):
        """Start polling memory in background thread"""
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, args=(interval,))
        self.poll_thread.daemon = True
        self.poll_thread.start()
    
    def _poll_loop(self, interval: float):
        """Background polling loop"""
        while self.running:
            if self.connected:
                for callback in self.callbacks:
                    try:
                        callback(self)
                    except Exception as e:
                        print(f"Callback error: {e}")
            time.sleep(interval)


class PokemonAchievementTracker:
    """Tracks Pokemon achievements using RetroArch memory reading"""
    
    def __init__(self, retroarch: RetroArchClient, achievement_definitions: Dict):
        self.retroarch = retroarch
        self.achievements = achievement_definitions.get("achievements", [])
        self.progress: Dict[str, Dict] = {}
        self.unlocked: set = set()
        self.on_unlock: Optional[Callable] = None
        
        # Initialize progress tracking
        for ach in self.achievements:
            self.progress[ach["id"]] = {
                "current": 0,
                "target": ach.get("target_value", 1),
                "unlocked": False
            }
    
    def set_unlock_callback(self, callback: Callable):
        """Set callback for when achievement is unlocked"""
        self.on_unlock = callback
    
    def check_achievements(self):
        """Check all achievements against current memory state"""
        for achievement in self.achievements:
            ach_id = achievement["id"]
            
            # Skip already unlocked
            if ach_id in self.unlocked:
                continue
            
            # Check memory condition
            memory_addr = achievement.get("memory_address")
            condition = achievement.get("memory_condition")
            
            if memory_addr and condition:
                value = self.retroarch.read_memory(memory_addr)
                if value is not None:
                    unlocked = self._evaluate_condition(value, condition)
                    if unlocked:
                        self._unlock_achievement(achievement)
    
    def _evaluate_condition(self, value: int, condition: str) -> bool:
        """Evaluate a memory condition"""
        condition = condition.strip()
        
        # Handle different condition types
        if condition.startswith(">="):
            try:
                target = int(condition[2:].strip())
                return value >= target
            except:
                pass
        elif condition.startswith("<="):
            try:
                target = int(condition[2:].strip())
                return value <= target
            except:
                pass
        elif condition.startswith(">"):
            try:
                target = int(condition[1:].strip())
                return value > target
            except:
                pass
        elif condition.startswith("<"):
            try:
                target = int(condition[1:].strip())
                return value < target
            except:
                pass
        elif condition.startswith("=="):
            try:
                target = int(condition[2:].strip())
                return value == target
            except:
                pass
        elif condition.startswith("!="):
            try:
                target = int(condition[2:].strip())
                return value != target
            except:
                pass
        elif condition.startswith("&"):
            # Bitwise AND check
            try:
                target = int(condition[1:].strip(), 16) if "x" in condition else int(condition[1:].strip())
                return (value & target) == target
            except:
                pass
        
        return False
    
    def _unlock_achievement(self, achievement: Dict):
        """Handle achievement unlock"""
        ach_id = achievement["id"]
        self.unlocked.add(ach_id)
        self.progress[ach_id]["unlocked"] = True
        
        print(f"🏆 Achievement Unlocked: {achievement['name']}!")
        
        if self.on_unlock:
            self.on_unlock(achievement)
    
    def get_progress(self) -> Dict:
        """Get current progress for all achievements"""
        return self.progress
    
    def get_unlocked_count(self) -> int:
        """Get number of unlocked achievements"""
        return len(self.unlocked)


# Example usage
if __name__ == "__main__":
    # Connect to RetroArch
    client = RetroArchClient()
    
    if client.connect():
        print("Connected!")
        
        # Get game info
        game = client.get_current_game()
        print(f"Game: {game}")
        
        # Read memory (example: check badge count in Pokemon)
        badge_value = client.read_memory("0x02024A6C", 1)
        print(f"Badge value: {badge_value}")
        
        # Disconnect
        client.disconnect()
    else:
        print("Could not connect. Make sure RetroArch is running with network commands enabled.")
        print("Enable in: Settings -> Network -> Network Command Enable")
