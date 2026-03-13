"""
Azahar RPC Client for PokeAchieve Tracker
Connects to Azahar's built-in RPC server for 3DS Pokemon game support (Gen 6/7)
"""
import socket
import struct
from typing import Optional, Tuple, List
from enum import IntEnum


class PacketType(IntEnum):
    """Azahar RPC packet types"""
    ReadMemory = 1
    WriteMemory = 2
    ProcessList = 3
    SetGetProcess = 4


class AzaharRPCClient:
    """
    Client for Azahar's built-in RPC server (UDP port 45987)
    
    Enable in Azahar: Emulation > Configure > Debug > "Enable RPC server"
    """
    
    DEFAULT_PORT = 45987
    DEFAULT_HOST = "127.0.0.1"
    PROTOCOL_VERSION = 1
    MAX_READ_SIZE = 1024
    
    # Gen 6/7 Memory Addresses (from ProjectPokemon)
    MEM_FCRAM = 0x08000000  # Main RAM base
    
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.packet_id = 0
        self.server_addr = (host, port)
        self.current_process: Optional[int] = None
        
    def _next_packet_id(self) -> int:
        """Get next packet ID"""
        self.packet_id += 1
        return self.packet_id
    
    def _send_packet(self, packet_type: PacketType, data: bytes = b'') -> None:
        """Send a packet to the RPC server via UDP"""
        if not self.socket:
            raise ConnectionError("Not connected to RPC server")
        
        header = struct.pack('<IIII', 
            self.PROTOCOL_VERSION,
            self._next_packet_id(),
            packet_type,
            len(data)
        )
        self.socket.sendto(header + data, self.server_addr)
    
    def _recv_packet(self) -> Tuple[PacketType, bytes]:
        """Receive a packet from the RPC server via UDP"""
        if not self.socket:
            raise ConnectionError("Not connected to RPC server")
        
        data, addr = self.socket.recvfrom(2048)
        if len(data) < 16:
            raise ValueError(f"Packet too short: {len(data)} bytes")
        
        version, packet_id, packet_type, data_size = struct.unpack('<IIII', data[:16])
        
        if version != self.PROTOCOL_VERSION:
            raise ValueError(f"Protocol version mismatch: got {version}")
        
        return PacketType(packet_type), data[16:16+data_size]
    
    def connect(self) -> bool:
        """Connect to Azahar's RPC server (UDP)"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(5.0)
            self.connected = True
            self.packet_id = 0
            return True
        except Exception as e:
            print(f"Failed to create socket: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Close UDP socket"""
        if self.socket:
            self.socket.close()
            self.socket = None
        self.connected = False
        self.current_process = None
    
    def is_connected(self) -> bool:
        """Check if socket is active"""
        return self.connected and self.socket is not None
    
    def read_memory(self, address, size: int = 1) -> Optional[int]:
        """
        Read memory from 3DS guest
        
        Args:
            address: Memory address (can be int or hex string)
            size: Number of bytes to read (1, 2, or 4)
        
        Returns:
            Integer value or None on error
        """
        if not self.connected:
            return None
        
        # Convert hex string to int if needed
        if isinstance(address, str):
            address = int(address, 16) if address.startswith('0x') else int(address)
        
        if size > self.MAX_READ_SIZE:
            # Read in chunks
            result = b''
            offset = 0
            while offset < size:
                chunk_size = min(self.MAX_READ_SIZE, size - offset)
                chunk = self._read_memory_raw(address + offset, chunk_size)
                if chunk is None:
                    return None
                result += chunk
                offset += chunk_size
            # Convert to int based on requested size
            if len(result) >= size:
                if size == 1:
                    return result[0]
                elif size == 2:
                    return struct.unpack('<H', result[:2])[0]
                elif size >= 4:
                    return struct.unpack('<I', result[:4])[0]
            return None
        
        data = self._read_memory_raw(address, size)
        if data is None:
            return None
        
        # Convert to integer (little-endian)
        if len(data) == 1:
            return data[0]
        elif len(data) == 2:
            return struct.unpack('<H', data)[0]
        elif len(data) >= 4:
            return struct.unpack('<I', data[:4])[0]
        return None
    
    def _read_memory_raw(self, address: int, size: int) -> Optional[bytes]:
        """Read raw memory bytes"""
        try:
            request_data = struct.pack('<II', address, size)
            self._send_packet(PacketType.ReadMemory, request_data)
            packet_type, data = self._recv_packet()
            
            if packet_type != PacketType.ReadMemory:
                return None
            
            return data
        except Exception as e:
            return None
    
    def get_process_list(self) -> Optional[List[dict]]:
        """Get list of running processes"""
        if not self.connected:
            return None
        
        try:
            request_data = struct.pack('<II', 0, 64)
            self._send_packet(PacketType.ProcessList, request_data)
            packet_type, data = self._recv_packet()
            
            if packet_type != PacketType.ProcessList or len(data) < 4:
                return None
            
            num_processes = struct.unpack('<I', data[:4])[0]
            processes = []
            offset = 4
            
            for i in range(num_processes):
                if offset + 0x14 > len(data):
                    break
                
                process_id = struct.unpack('<I', data[offset:offset+4])[0]
                title_id = struct.unpack('<Q', data[offset+4:offset+12])[0]
                name_bytes = data[offset+12:offset+20]
                process_name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
                
                processes.append({
                    'pid': process_id,
                    'title_id': title_id,
                    'name': process_name
                })
                offset += 0x14
            
            return processes
        except Exception as e:
            return None
    
    def select_process(self, process_id: int) -> bool:
        """Select a process for memory operations"""
        if not self.connected:
            return False
        
        try:
            request_data = struct.pack('<II', 0, process_id)
            self._send_packet(PacketType.SetGetProcess, request_data)
            packet_type, data = self._recv_packet()
            
            if packet_type == PacketType.SetGetProcess and len(data) >= 8:
                self.current_process = process_id
                return True
            return False
        except Exception as e:
            return False
    
    def find_pokemon_process(self) -> Optional[int]:
        """Find the Pokemon game process"""
        processes = self.get_process_list()
        if not processes:
            return None
        
        for proc in processes:
            name = proc.get('name', '').lower()
            # Common Pokemon game process names in Azahar
            if any(x in name for x in ['kujira', 'pokemon', 'poke', 'x', 'y', 'omega', 'alpha', 'sun', 'moon']):
                return proc['pid']
        
        # Return first process if only one (likely the game)
        if len(processes) == 1:
            return processes[0]['pid']
        
        return None
