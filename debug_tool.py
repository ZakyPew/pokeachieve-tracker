#!/usr/bin/env python3
"""
PokeAchieve Tracker Debug Tool
Run this on your gaming machine to see what's happening
"""

import socket
import json
import time
import sys
from pathlib import Path

# Add tracker to path
sys.path.insert(0, str(Path(__file__).parent / "tracker"))

def test_memory_reading():
    """Test if we can read Pokemon memory"""
    print("🔍 PokeAchieve Tracker Debug Tool")
    print("=" * 60)
    
    # Connect to RetroArch
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    
    # Test GET_STATUS
    print("\n📤 Testing GET_STATUS...")
    try:
        sock.sendto(b"GET_STATUS\n", ("127.0.0.1", 55355))
        response, addr = sock.recvfrom(4096)
        status = response.decode().strip()
        print(f"📥 Response: {status}")
        
        if "PAUSED" in status or "PLAYING" in status:
            parts = status.replace("GET_STATUS ", "").split(",")
            if len(parts) >= 2:
                print(f"   Game detected: {parts[1]}")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   Is RetroArch running with Network Commands enabled?")
        return
    
    # Test memory reading (Pokemon Red Pokedex flags)
    print("\n📤 Testing memory read (Pokemon Red Pokedex)...")
    print("   Address: 0xD2F7 (first byte of Pokedex flags)")
    try:
        sock.sendto(b"READ_CORE_MEMORY 0xD2F7 1\n", ("127.0.0.1", 55355))
        response, addr = sock.recvfrom(4096)
        mem_response = response.decode().strip()
        print(f"📥 Response: {mem_response}")
        
        if mem_response.startswith("READ_CORE_MEMORY"):
            parts = mem_response.split()
            if len(parts) >= 3:
                try:
                    value = int(parts[2], 16)
                    print(f"   Value: 0x{value:02X} ({value})")
                    print(f"   This byte contains flags for Pokemon #1-8")
                    
                    # Decode which Pokemon are caught
                    caught = []
                    for bit in range(8):
                        if (value >> bit) & 1:
                            caught.append(bit + 1)
                    if caught:
                        print(f"   Caught in this byte: {caught}")
                    else:
                        print("   No Pokemon caught in this byte yet")
                except:
                    print("   Could not parse value")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test party count
    print("\n📤 Testing party count read...")
    print("   Address: 0xD163 (Pokemon Red party count)")
    try:
        sock.sendto(b"READ_CORE_MEMORY 0xD163 1\n", ("127.0.0.1", 55355))
        response, addr = sock.recvfrom(4096)
        mem_response = response.decode().strip()
        print(f"📥 Response: {mem_response}")
        
        if mem_response.startswith("READ_CORE_MEMORY"):
            parts = mem_response.split()
            if len(parts) >= 3:
                try:
                    value = int(parts[2], 16)
                    print(f"   Party count: {value} Pokemon")
                except:
                    print("   Could not parse value")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    sock.close()
    
    print("\n" + "=" * 60)
    print("\n💡 What to check:")
    print("   1. Is a Pokemon ROM loaded in RetroArch?")
    print("   2. Are achievements appearing in the tracker GUI?")
    print("   3. Is the API key configured in tracker settings?")
    print("   4. Check the tracker log tab for errors")

if __name__ == "__main__":
    test_memory_reading()
