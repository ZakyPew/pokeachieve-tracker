# RetroArch Integration Module
# Connects to RetroArch via network command interface for real-time achievement tracking

import socket
import json
import time
import threading
from typing import Callable, Optional, Dict, List, Tuple

class RetroArchClient:
    """Client for connecting to RetroArch network command interface via UDP"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 55355):
        self.host = host
        self.port = port
        self.address: Tuple[str, int] = (host, port)
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        self.callbacks: List[Callable] = []
        self.poll_thread: Optional[threading.Thread] = None
    
    def connect(self) -> bool:
        """Connect to RetroArch (UDP doesn't truly connect, but we create the socket)"""
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(5)
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
            # Send command via UDP
            self.socket.sendto(f"{command}\n".encode(), self.address)
            # Receive response
            response, addr = self.socket.recvfrom(4096)
            return response.decode().strip()
        except socket.timeout:
            return None
        except Exception as e:
            print(f"Command failed: {e}")
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
        response = self.send_command(f"READ_CORE_MEMORY {address} {num_bytes}")
        if response and response.startswith("READ_CORE_MEMORY"):
            parts = response.split()
            if len(parts) >= 3:
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
        """Start polling RetroArch for memory changes"""
        if self.running:
            return
        
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, args=(interval,))
        self.poll_thread.daemon = True
        self.poll_thread.start()
    
    def stop_polling(self):
        """Stop polling RetroArch"""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=2)
            self.poll_thread = None
    
    def _poll_loop(self, interval: float):
        """Main polling loop"""
        while self.running:
            try:
                for callback in self.callbacks:
                    try:
                        callback(self)
                    except Exception as e:
                        print(f"Callback error: {e}")
                time.sleep(interval)
            except Exception as e:
                print(f"Poll loop error: {e}")
                time.sleep(interval)
