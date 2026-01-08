#!/usr/bin/env python3
"""
wyndrvr - Latency and Bandwidth Utility
A UDP-based network testing tool for measuring latency and bandwidth.
"""


__version__ = "0.6"
__version_notes__ = """
Version 0.6:
- Added PortType enum for type-safe port type handling (CONTROL, UPLOAD, DOWNLOAD)
- Heartbeat messages now use heartbeat_key in data_channel field for identification
- Implemented per-packet sequence numbering with automatic rollover at 2^64
- Each unique (port, data_channel) combination maintains independent sequence counter
- Server-side latency statistics now tracked per-client connection
- Fixed send_heartbeat to only increment sequences when actually sending

Version 0.5:
- Bumped version to 0.5.
- Fixed indentation bug causing an IndentationError on server startup.
- Added graceful server shutdown to print per-channel latency summary on Ctrl+C.
- Improved heartbeat handling: binary MessagePacket format, per-port heartbeats, and latency aggregation.

Version 0.4:
- Added command line arguments for all config settings (--bind-addr, --bind-port, etc.)
- Config file creation/editing with command line arguments
- Warning when editing existing config files with list of changes
- All timing and parallelization settings configurable via CLI

Version 0.3:
- Added --config option to specify custom config file location
- Added --create-config option to generate default config file
- Added server_block_time and client_block_time settings (default 100ms)
- Client socket blocking uses configured block_time (non-blocking if zero)
- Config path can be directory or full file path
- Client loads client_block_time from config file

Version 0.2:
- Refactored to use client_comm_loop and server_comm_loop
- Heartbeat handling integrated into main communication loops
- Removed separate heartbeat thread (unless port_parallelability is THREAD/PROCESS)
- Server loop handles port assignments and heartbeat exchanges
- Client loop handles heartbeat timing and responses

Version 0.1:
- Initial implementation with heartbeat exchange protocol
- Client initiates heartbeat, server echoes, client sends final echo
- Both client and server calculate and report latency to stderr
- Heartbeat rate changed to milliseconds (default 5000ms)
"""

import argparse
import socket
import sys
import os
import threading
import multiprocessing
import time
import select
import struct
import json
from pathlib import Path
from enum import Enum
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
import signal


class ParallelMode(Enum):
    """Parallelization modes for server operations"""
    SINGLE = "SINGLE"
    THREAD = "THREAD"
    PROCESS = "PROCESS"


class MessageType(Enum):
    """Message types for packet header"""
    HEARTBEAT_0 = 0
    HEARTBEAT_1 = 1
    HEARTBEAT_2 = 2
    FLOW_CONTROL = 3
    BANDWIDTH_TEST = 4
    DATA = 5


class PortType(Enum):
    """Port types for client connections"""
    CONTROL = "control"
    UPLOAD = "upload"
    DOWNLOAD = "download"


class MessagePacket:
    """Helper to format/unformat the 20-byte header + JSON payload packets.

    Header layout (20 bytes):
      1 byte  - MessageType (int)
      3 bytes - data_channel (unsigned int, big-endian)
      8 bytes - channel_sequence_number (unsigned long long, big-endian)
      8 bytes - sequence_offset (unsigned long long, big-endian)
    Remaining bytes: UTF-8 encoded JSON payload
    """

    HEADER_LEN = 20

    @classmethod
    def format_packet(cls, msg_type, data_channel: int, channel_sequence_number: int, sequence_offset: int, json_obj) -> bytes:
        mt = int(msg_type.value) if isinstance(msg_type, MessageType) else int(msg_type)
        # 1 byte message type
        header = bytes([mt])
        # 3 bytes data_channel
        header += int(data_channel).to_bytes(3, 'big')
        # 8 bytes channel_sequence_number
        header += struct.pack('>Q', int(channel_sequence_number))
        # 8 bytes sequence_offset
        header += struct.pack('>Q', int(sequence_offset))

        body = json.dumps(json_obj).encode('utf-8') if json_obj is not None else b''

        return header + body

    @classmethod
    def parse_packet(cls, data: bytes):
        if not data or len(data) < cls.HEADER_LEN:
            raise ValueError('Packet too short to parse')

        mt_val = data[0]
        try:
            mt = MessageType(mt_val)
        except ValueError:
            mt = mt_val

        data_channel = int.from_bytes(data[1:4], 'big')
        channel_sequence_number = struct.unpack('>Q', data[4:12])[0]
        sequence_offset = struct.unpack('>Q', data[12:20])[0]

        json_bytes = data[20:]
        if json_bytes:
            try:
                json_obj = json.loads(json_bytes.decode('utf-8'))
            except Exception:
                json_obj = None
        else:
            json_obj = None

        return mt, data_channel, channel_sequence_number, sequence_offset, json_obj


@dataclass
class ServerConfig:
    """Server configuration settings"""
    bind_addr: str = "0.0.0.0"
    bind_port: int = 6711
    port_ranges: List[Tuple[int, int]] = None
    connection_parallelibility: ParallelMode = ParallelMode.SINGLE
    port_parallelability: ParallelMode = ParallelMode.SINGLE
    incoming_blocking_level: int = 0  # microseconds
    incoming_sleep: int = 0  # microseconds
    max_send_time: int = 0  # microseconds
    send_sleep: int = 0  # microseconds
    heartbeat_rate: int = 5000  # milliseconds (5 seconds)
    adjustment_delay: int = 1000000  # microseconds (1 second)
    flow_control_rate: int = 10  # divider for adjustment_delay
    server_block_time: int = 100  # milliseconds
    client_block_time: int = 100  # milliseconds
    
    def __post_init__(self):
        if self.port_ranges is None:
            self.port_ranges = [(7000, 8000)]


class PortManager:
    """Manages allocation of ports from configured port ranges"""
    
    def __init__(self, port_ranges: List[Tuple[int, int]]):
        self.port_ranges = port_ranges
        self.used_ports = set()
        self.lock = threading.Lock()
    
    def allocate_ports(self, count: int = 3) -> Optional[List[int]]:
        """Allocate a specified number of ports"""
        with self.lock:
            available_ports = []
            for start, end in self.port_ranges:
                for port in range(start, end + 1):
                    if port not in self.used_ports:
                        available_ports.append(port)
            
            if len(available_ports) < count:
                return None
            
            return available_ports[:count]
    
    def mark_ports_used(self, ports: List[int]):
        """Mark ports as used"""
        with self.lock:
            for port in ports:
                self.used_ports.add(port)
    
    def release_ports(self, ports: List[int]):
        """Release previously allocated ports"""
        with self.lock:
            for port in ports:
                self.used_ports.discard(port)


class ServerClientComms:
    """Handles communication with a specific client over three UDP ports"""
    
    def __init__(self, client_addr: Tuple[str, int], bind_addr: str, port_manager: PortManager, server_ref: 'WyndServer' = None):
        self.client_addr = client_addr
        self.bind_addr = bind_addr
        self.server = server_ref
        self.control_port = None
        self.upload_port = None
        self.download_port = None
        self.control_socket = None
        self.upload_socket = None
        self.download_socket = None
        self.heartbeat_key = int(time.time() * 1000) % 60001
        self.comms_up = False
        self.control_received = False
        self.upload_received = False
        self.download_received = False
        # Sequence tracking: key is (port, data_channel), value is sequence number
        self._sequences = {}
        # Latency stats per channel for this client
        self._latency_stats: Dict[str, Dict[str, float]] = {
            'CONTROL':  {'sum': 0.0, 'count': 0},
            'UPLOAD':   {'sum': 0.0, 'count': 0},
            'DOWNLOAD': {'sum': 0.0, 'count': 0},
        }
        
        # Try to allocate and bind three ports
        if not self._initialize_sockets(port_manager):
            raise RuntimeError("Failed to allocate ports for client")
    
    def _initialize_sockets(self, port_manager: PortManager) -> bool:
        """Initialize three sockets for the client, trying ports until successful"""
        available_ports = port_manager.allocate_ports(count=100)  # Get many candidates
        if not available_ports or len(available_ports) < 3:
            return False
        
        allocated_ports = []
        sockets = []
        
        # Try to bind three sockets
        for port in available_ports:
            if len(allocated_ports) >= 3:
                break
            
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind((self.bind_addr, port))
                sock.setblocking(False)
                allocated_ports.append(port)
                sockets.append(sock)
            except OSError:
                # Port binding failed, try next port
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
                continue
        
        if len(allocated_ports) < 3:
            # Clean up any sockets we did create
            for sock in sockets:
                try:
                    sock.close()
                except:
                    pass
            return False
        
        # Success - assign the ports and sockets
        self.control_port = allocated_ports[0]
        self.upload_port = allocated_ports[1]
        self.download_port = allocated_ports[2]
        self.control_socket = sockets[0]
        self.upload_socket = sockets[1]
        self.download_socket = sockets[2]
        
        # Mark ports as used
        port_manager.mark_ports_used(allocated_ports)
        
        return True
    
    def get_ports(self) -> Tuple[int, int, int]:
        """Return the three port numbers"""
        return (self.control_port, self.upload_port, self.download_port)
    
    def get_heartbeat_key(self) -> bytes:
        """Return the heartbeat key"""
        return self.heartbeat_key

    def get_and_increment_sequence(self, port: int, data_channel: int) -> int:
        """Get current sequence number and increment it for the given port/channel combination"""
        key = (port, data_channel)
        seq = self._sequences.get(key, 0)
        # Increment and handle rollover at max 64-bit unsigned int
        self._sequences[key] = (seq + 1) % (2**64)
        return seq

    def record_latency(self, port_label: str, latency_ms: float):
        """Record latency measurement for this client"""
        label = port_label.upper()
        if label not in self._latency_stats:
            self._latency_stats[label] = {'sum': 0.0, 'count': 0}
        self._latency_stats[label]['sum'] += float(latency_ms)
        self._latency_stats[label]['count'] += 1

    def print_latency_summary(self):
        """Print latency summary for this client"""
        print(f"  Client {self.client_addr[0]}:{self.client_addr[1]}:")
        for label, data in self._latency_stats.items():
            if data['count'] > 0:
                avg = data['sum'] / data['count']
                print(f"    {label:9}: avg={avg:.2f} ms over {int(data['count'])} samples")
            else:
                print(f"    {label:9}: no samples")
    
    def handle_client_connection(self, data: bytes, port_type: PortType, src_addr: Optional[Tuple[str,int]] = None) -> bool:
        """Handle data received on one of the client's ports
        
        Args:
            data: The received data
            port_type: PortType enum value (CONTROL, UPLOAD, or DOWNLOAD)
            
        Returns:
            True if data was received and processed, False otherwise
        """
        if not data:
            return False
        
        # Mark that this port has received data
        if port_type == PortType.CONTROL:
            self.control_received = True
        elif port_type == PortType.UPLOAD:
            self.upload_received = True
        elif port_type == PortType.DOWNLOAD:
            self.download_received = True
        
        # Check if all three ports have received at least one packet
        if self.control_received and self.upload_received and self.download_received:
            if not self.comms_up:
                print(f"Client {self.client_addr[0]}:{self.client_addr[1]} - all ports active, comms_up=True")
                sys.stdout.flush()
            self.comms_up = True
        
        # Try parse as MessagePacket and handle heartbeat latency printing or replies
        try:
            mt, data_channel, channel_sequence_number, sequence_offset, json_obj = MessagePacket.parse_packet(data)
        except Exception:
            return True

        # Check if this is a heartbeat message (data_channel == heartbeat_key)
        is_heartbeat = (data_channel == self.heartbeat_key)

        # Only compute/print latency for heartbeat messages
        if is_heartbeat and isinstance(mt, MessageType):

            # HEARTBEAT_0 -> server should reply with HEARTBEAT_1 on this same socket
            if mt == MessageType.HEARTBEAT_0:
                server_time = time.time()
                client_ts = None
                if isinstance(json_obj, dict):
                    client_ts = json_obj.get('timestamp')

                resp_json = {'client_timestamp': client_ts, 'server_timestamp': server_time}
                # Determine which port we're responding on and get sequence number
                send_port = None
                if port_type == PortType.CONTROL:
                    send_port = self.control_port
                elif port_type == PortType.UPLOAD:
                    send_port = self.upload_port
                elif port_type == PortType.DOWNLOAD:
                    send_port = self.download_port
                seq_num = self.get_and_increment_sequence(send_port, data_channel) if send_port else 0
                resp = MessagePacket.format_packet(MessageType.HEARTBEAT_1, data_channel, seq_num, sequence_offset, resp_json)
                # send on appropriate socket back to the source address if available
                if src_addr:
                    if port_type == PortType.CONTROL and self.control_socket:
                        try:
                            self.control_socket.sendto(resp, src_addr)
                        except Exception:
                            pass
                    elif port_type == PortType.UPLOAD and self.upload_socket:
                        try:
                            self.upload_socket.sendto(resp, src_addr)
                        except Exception:
                            pass
                    elif port_type == PortType.DOWNLOAD and self.download_socket:
                        try:
                            self.download_socket.sendto(resp, src_addr)
                        except Exception:
                            pass

            # HEARTBEAT_2 -> server computes latency when receiving final echo on this port
            if mt == MessageType.HEARTBEAT_2:
                server_ts = None
                if isinstance(json_obj, dict):
                    server_ts = json_obj.get('server_timestamp')

                if server_ts is not None:
                    current_time = time.time()
                    latency = (current_time - server_ts) * 1000
                    port_label = {
                        PortType.CONTROL: 'CONTROL',
                        PortType.UPLOAD: 'UPLOAD',
                        PortType.DOWNLOAD: 'DOWNLOAD'
                    }.get(port_type, 'UNKNOWN')
                    print(f"Server latency on {port_label:9} to {self.client_addr[0]}:{self.client_addr[1]}: {latency:.2f} ms", file=sys.stderr)
                    sys.stderr.flush()
                    self.record_latency(port_label, latency)

        return True
    
    def close(self):
        """Close all sockets"""
        for sock in [self.control_socket, self.upload_socket, self.download_socket]:
            if sock:
                try:
                    sock.close()
                except:
                    pass


class WyndServer:
    """UDP Server for wyndrvr"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.port_manager = PortManager(config.port_ranges)
        self.running = False
        self.main_socket = None
        self.client_connections = {}  # client_addr -> ServerClientComms instance

    def print_latency_summary(self):
        """Print latency summary for all clients"""
        print("\nServer latency summary by client:")
        if not self.client_connections:
            print("  No client connections")
            return
        for client_addr, client_comms in self.client_connections.items():
            client_comms.print_latency_summary()
    
    def load_config(self, config_path: Path) -> ServerConfig:
        """Load configuration from file"""
        config = ServerConfig()
        
        if not config_path.exists():
            return config
        
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'bind_addr':
                            config.bind_addr = value
                        elif key == 'bind_port':
                            config.bind_port = int(value)
                        elif key == 'port_ranges':
                            # Parse format: "7000-8000,9000-9500"
                            ranges = []
                            for range_str in value.split(','):
                                start, end = map(int, range_str.split('-'))
                                ranges.append((start, end))
                            config.port_ranges = ranges
                        elif key == 'connection_parallelibility':
                            config.connection_parallelibility = ParallelMode[value.upper()]
                        elif key == 'port_parallelability':
                            config.port_parallelability = ParallelMode[value.upper()]
                        elif key == 'incoming_blocking_level':
                            config.incoming_blocking_level = int(value)
                        elif key == 'incoming_sleep':
                            config.incoming_sleep = int(value)
                        elif key == 'max_send_time':
                            config.max_send_time = int(value)
                        elif key == 'send_sleep':
                            config.send_sleep = int(value)
                        elif key == 'heartbeat_rate':
                            config.heartbeat_rate = int(value)
                        elif key == 'adjustment_delay':
                            config.adjustment_delay = int(value)
                        elif key == 'flow_control_rate':
                            config.flow_control_rate = int(value)
                        elif key == 'server_block_time':
                            config.server_block_time = int(value)
                        elif key == 'client_block_time':
                            config.client_block_time = int(value)
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
        
        return config
    
    def create_default_config(self, config_path: Path) -> bool:
        """Create a default configuration file"""
        default_config = """# wyndrvr configuration file
# All time values: microseconds (unless specified otherwise)

# Server bind settings
bind_addr=0.0.0.0
bind_port=6711

# Port ranges for client connections (format: start-end,start-end)
port_ranges=7000-8000

# Parallelization modes: SINGLE, THREAD, PROCESS
connection_parallelibility=SINGLE
port_parallelability=SINGLE

# Incoming packet handling
incoming_blocking_level=0
incoming_sleep=0

# Outgoing packet handling
max_send_time=0
send_sleep=0

# Heartbeat and flow control (milliseconds for heartbeat_rate)
heartbeat_rate=5000
adjustment_delay=1000000
flow_control_rate=10

# Socket blocking times (milliseconds)
server_block_time=100
client_block_time=100
"""
        
        try:
            # Create directory if it doesn't exist
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write config file
            with open(config_path, 'w') as f:
                f.write(default_config)
            
            print(f"Created default configuration file: {config_path}")
            return True
        except Exception as e:
            print(f"Error creating config file: {e}", file=sys.stderr)
            return False
    
    def update_config_from_args(self, config_path: Path, args) -> bool:
        """Update existing config file or create new one with values from command line args"""
        is_new = not config_path.exists()
        
        # Start with default config
        if is_new:
            config_dict = {
                'bind_addr': '0.0.0.0',
                'bind_port': '6711',
                'port_ranges': '7000-8000',
                'connection_parallelibility': 'SINGLE',
                'port_parallelability': 'SINGLE',
                'incoming_blocking_level': '0',
                'incoming_sleep': '0',
                'max_send_time': '0',
                'send_sleep': '0',
                'heartbeat_rate': '5000',
                'adjustment_delay': '1000000',
                'flow_control_rate': '10',
                'server_block_time': '100',
                'client_block_time': '100'
            }
        else:
            # Load existing config
            config_dict = {}
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config_dict[key.strip()] = value.strip()
        
        # Track changes
        changes = []
        
        # Update with command line arguments - loop through all config parameters
        config_params = [
            ('bind_addr', 'bind_addr', False),
            ('bind_port', 'bind_port', True),
            ('port_ranges', 'port_ranges', False),
            ('connection_parallelibility', 'connection_parallelibility', False),
            ('port_parallelability', 'port_parallelability', False),
            ('incoming_blocking_level', 'incoming_blocking_level', True),
            ('incoming_sleep', 'incoming_sleep', True),
            ('max_send_time', 'max_send_time', True),
            ('send_sleep', 'send_sleep', True),
            ('heartbeat_rate', 'heartbeat_rate', True),
            ('adjustment_delay', 'adjustment_delay', True),
            ('flow_control_rate', 'flow_control_rate', True),
            ('server_block_time', 'server_block_time', True),
            ('client_block_time', 'client_block_time', True),
        ]
        
        for arg_name, config_key, convert_to_str in config_params:
            arg_value = getattr(args, arg_name, None)
            if arg_value is not None:
                old_val = config_dict.get(config_key)
                new_val = str(arg_value) if convert_to_str else arg_value
                config_dict[config_key] = new_val
                if not is_new and old_val != new_val:
                    changes.append(f"{config_key}: {old_val} -> {arg_value}")
        
        try:
            # Create directory if needed
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write config file
            with open(config_path, 'w') as f:
                f.write("# wyndrvr configuration file\n")
                f.write("# All time values: microseconds (unless specified otherwise)\n\n")
                
                f.write("# Server bind settings\n")
                f.write(f"bind_addr={config_dict.get('bind_addr', '0.0.0.0')}\n")
                f.write(f"bind_port={config_dict.get('bind_port', '6711')}\n\n")
                
                f.write("# Port ranges for client connections (format: start-end,start-end)\n")
                f.write(f"port_ranges={config_dict.get('port_ranges', '7000-8000')}\n\n")
                
                f.write("# Parallelization modes: SINGLE, THREAD, PROCESS\n")
                f.write(f"connection_parallelibility={config_dict.get('connection_parallelibility', 'SINGLE')}\n")
                f.write(f"port_parallelability={config_dict.get('port_parallelability', 'SINGLE')}\n\n")
                
                f.write("# Incoming packet handling\n")
                f.write(f"incoming_blocking_level={config_dict.get('incoming_blocking_level', '0')}\n")
                f.write(f"incoming_sleep={config_dict.get('incoming_sleep', '0')}\n\n")
                
                f.write("# Outgoing packet handling\n")
                f.write(f"max_send_time={config_dict.get('max_send_time', '0')}\n")
                f.write(f"send_sleep={config_dict.get('send_sleep', '0')}\n\n")
                
                f.write("# Heartbeat and flow control (milliseconds for heartbeat_rate)\n")
                f.write(f"heartbeat_rate={config_dict.get('heartbeat_rate', '5000')}\n")
                f.write(f"adjustment_delay={config_dict.get('adjustment_delay', '1000000')}\n")
                f.write(f"flow_control_rate={config_dict.get('flow_control_rate', '10')}\n\n")
                
                f.write("# Socket blocking times (milliseconds)\n")
                f.write(f"server_block_time={config_dict.get('server_block_time', '100')}\n")
                f.write(f"client_block_time={config_dict.get('client_block_time', '100')}\n")
            
            if is_new:
                print(f"Created configuration file: {config_path}")
            else:
                if changes:
                    print(f"WARNING: Edited existing configuration file: {config_path}")
                    print("Changes made:")
                    for change in changes:
                        print(f"  {change}")
                else:
                    print(f"Configuration file unchanged: {config_path}")
            
            return True
        except Exception as e:
            print(f"Error updating config file: {e}", file=sys.stderr)
            return False
    
    def start(self):
        """Start the server"""
        self.running = True
        
        # Create main socket
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.main_socket.bind((self.config.bind_addr, self.config.bind_port))
        
        # Set socket timeout based on server_block_time
        if self.config.server_block_time > 0:
            timeout = self.config.server_block_time / 1000  # Convert milliseconds to seconds
            self.main_socket.settimeout(timeout)
        else:
            self.main_socket.setblocking(False)
        
        print(f"Server started on {self.config.bind_addr}:{self.config.bind_port}")
        sys.stdout.flush()
        
        # Main server loop
        self.server_comm_loop()
    
    def server_comm_loop(self):
        """Main server communication loop - handles port assignments and heartbeats"""
        while self.running:
            try:
                # Receive incoming packets on main socket
                data, client_addr = self.main_socket.recvfrom(4096)
                
                # Handle new client connections or heartbeat messages
                if data.startswith(b"CONNECT") or client_addr not in self.client_connections:
                    # Create ServerClientComms instance for new client
                    if client_addr not in self.client_connections:
                        try:
                            client_comms = ServerClientComms(client_addr, self.config.bind_addr, self.port_manager, server_ref=self)
                            self.client_connections[client_addr] = client_comms
                            
                            control_port, upload_port, download_port = client_comms.get_ports()
                            
                            print(f"Client connected: {client_addr[0]}:{client_addr[1]}")
                            print(f"  Control Port: {control_port}")
                            print(f"  Upload Port: {upload_port}")
                            print(f"  Download Port: {download_port}")
                            sys.stdout.flush()
                        except RuntimeError as e:
                            print(f"Failed to allocate ports for client {client_addr}: {e}", file=sys.stderr)
                            continue
                    
                    # Send port information if comms not yet up
                    client_comms = self.client_connections[client_addr]
                    if not client_comms.comms_up:
                        ports = client_comms.get_ports()
                        heartbeat_key = client_comms.get_heartbeat_key()
                        response = f"{ports[0]},{ports[1]},{ports[2]},{heartbeat_key}".encode()
                        self.main_socket.sendto(response, client_addr)
                else:
                    # Try parsing as our binary MessagePacket (heartbeat, etc.)
                    try:
                        mt, data_channel, channel_seq, seq_offset, json_obj = MessagePacket.parse_packet(data)
                        # Only handle heartbeat types here
                        if isinstance(mt, MessageType) and mt in (MessageType.HEARTBEAT_0, MessageType.HEARTBEAT_1, MessageType.HEARTBEAT_2):
                            self.handle_heartbeat_message(client_addr, data)
                    except Exception:
                        # Not a MessagePacket - ignore or handled elsewhere
                        pass
                        
            except socket.timeout:
                pass
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"Error in server loop: {e}", file=sys.stderr)
            
            # Poll all client sockets for data
            for client_addr, client_comms in list(self.client_connections.items()):
                # Poll control socket
                try:
                    data, src = client_comms.control_socket.recvfrom(4096)
                    #print(f"received {len(data)} bytes of packet data on control port")
                    client_comms.handle_client_connection(data, PortType.CONTROL, src)
                except BlockingIOError:
                    pass
                except Exception as e:
                    pass
                
                # Poll upload socket
                try:
                    data, src = client_comms.upload_socket.recvfrom(4096)
                    #print(f"received {len(data)} bytes of packet data on upload port")
                    client_comms.handle_client_connection(data, PortType.UPLOAD, src)
                except BlockingIOError:
                    pass
                except Exception as e:
                    pass
                
                # Poll download socket
                try:
                    data, src = client_comms.download_socket.recvfrom(4096)
                    #print(f"received {len(data)} bytes of packet data on download port")
                    client_comms.handle_client_connection(data, PortType.DOWNLOAD, src)
                except BlockingIOError:
                    pass
                except Exception as e:
                    pass
            
            # Sleep if configured
            if self.config.incoming_sleep > 0:
                time.sleep(self.config.incoming_sleep / 1_000_000)
    
    def handle_heartbeat_message(self, client_addr: Tuple[str, int], data: bytes):
        """Handle heartbeat MessagePacket messages and reply on receiving socket."""
        try:
            mt, data_channel, channel_seq, seq_offset, json_obj = MessagePacket.parse_packet(data)
        except Exception:
            return

        # HEARTBEAT_0: server should reply with HEARTBEAT_1 containing timestamps
        if mt == MessageType.HEARTBEAT_0:
            client_timestamp = None
            if isinstance(json_obj, dict):
                client_timestamp = json_obj.get('timestamp')

            server_time = time.time()
            # mark the last receiving socket so handler can reply on the same socket
            try:
                self._last_recv_sock = self.main_socket
            except Exception:
                self._last_recv_sock = None
            resp_json = {'client_timestamp': client_timestamp, 'server_timestamp': server_time}
            resp = MessagePacket.format_packet(MessageType.HEARTBEAT_1, data_channel, channel_seq, seq_offset, resp_json)
            # send reply on the socket that received it (src_sock) or fallback to main_socket
            out_sock = getattr(self, 'main_socket', None)
            try:
                # if caller provided a src_sock (set as attribute before calling), use it
                if hasattr(self, '_last_recv_sock') and self._last_recv_sock is not None:
                    out_sock = self._last_recv_sock
            except Exception:
                pass

            try:
                out_sock.sendto(resp, client_addr)
            except Exception:
                pass
            return

        # HEARTBEAT_2: final echo from client - calculate latency at server
        if mt == MessageType.HEARTBEAT_2:
            client_timestamp = None
            server_timestamp = None
            if isinstance(json_obj, dict):
                client_timestamp = json_obj.get('client_timestamp')
                server_timestamp = json_obj.get('server_timestamp')

            current_time = time.time()
            if server_timestamp is not None:
                latency = (current_time - server_timestamp) * 1000  # ms
                print(f"Server latency (MAIN) to {client_addr[0]}:{client_addr[1]}: {latency:.2f} ms", file=sys.stderr)
                sys.stderr.flush()
            return
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.main_socket:
            self.main_socket.close()
        for client_comms in self.client_connections.values():
            client_comms.close()


class WyndClient:
    """UDP Client for wyndrvr"""
    
    def __init__(self, server_addr: str, server_port: int, block_time: int = 100):
        self.server_addr = server_addr
        self.server_port = server_port
        self.main_socket = None
        self.control_socket = None
        self.upload_socket = None
        self.download_socket = None
        self.running = False
        self.heartbeat_interval = 5.0  # seconds
        self.last_heartbeat = 0
        self.block_time = block_time  # milliseconds
        self.heartbeat_key = None  # Will be set after connecting
        # Sequence tracking: key is (port, data_channel), value is sequence number
        self._sequences = {}
        # client-side latency stats
        self._latency_stats = {
            #'MAIN': {'sum': 0.0, 'count': 0},
            'CONTROL': {'sum': 0.0, 'count': 0},
            'UPLOAD': {'sum': 0.0, 'count': 0},
            'DOWNLOAD': {'sum': 0.0, 'count': 0},
        }

    def record_latency(self, port_label: str, latency_ms: float):
        label = port_label.upper()
        if label not in self._latency_stats:
            self._latency_stats[label] = {'sum': 0.0, 'count': 0}
        self._latency_stats[label]['sum'] += float(latency_ms)
        self._latency_stats[label]['count'] += 1

    def print_latency_summary(self):
        print("\nClient latency summary:")
        for label, data in self._latency_stats.items():
            if data['count'] > 0:
                avg = data['sum'] / data['count']
                print(f"  {label:9}: avg={avg:.2f} ms over {int(data['count'])} samples")
            else:
                print(f"  {label:9}: no samples")

    def get_and_increment_sequence(self, port: int, data_channel: int) -> int:
        """Get current sequence number and increment it for the given port/channel combination"""
        key = (port, data_channel)
        seq = self._sequences.get(key, 0)
        # Increment and handle rollover at max 64-bit unsigned int
        self._sequences[key] = (seq + 1) % (2**64)
        return seq
    
    def start(self):
        """Start the client and connect to server"""
        self.running = True
        
        # Create main socket
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        print(f"Connecting to server {self.server_addr}:{self.server_port}")
        sys.stdout.flush()
        
        # Send initial connection request
        self.main_socket.sendto(b"CONNECT", (self.server_addr, self.server_port))
        
        # Wait for port assignment
        self.main_socket.settimeout(5.0)
        try:
            
            # Parse response: "port1,port2,port3,heartbeat_key"
            data, _ = self.main_socket.recvfrom(4096)
            ports_str = data.decode()
            self.control_port, self.upload_port, self.download_port, self.heartbeat_key = map(int, ports_str.split(','))
            
            print(f"Received port assignment:")
            print(f"  Control Port: {self.control_port}")
            print(f"  Upload Port: {self.upload_port}")
            print(f"  Download Port: {self.download_port}")       
            print(f"  Heartbeat Key: {self.heartbeat_key}")
            
            # Create sockets for each port
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.upload_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.download_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Set per-port socket timeouts/blocking consistent with main socket
            if self.block_time > 0:
                per_timeout = self.block_time / 1000
                self.control_socket.settimeout(per_timeout)
                self.upload_socket.settimeout(per_timeout)
                self.download_socket.settimeout(per_timeout)
            else:
                self.control_socket.setblocking(False)
                self.upload_socket.setblocking(False)
                self.download_socket.setblocking(False)

            # Send formatted HEARTBEAT_0 to each assigned server port (using heartbeat_key in data_channel)
            ts = time.time()
            seq_ctrl = self.get_and_increment_sequence(self.control_port, self.heartbeat_key)
            seq_up = self.get_and_increment_sequence(self.upload_port, self.heartbeat_key)
            seq_down = self.get_and_increment_sequence(self.download_port, self.heartbeat_key)
            msg_ctrl = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_ctrl, 0, {'timestamp': ts})
            msg_up = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_up, 0, {'timestamp': ts})
            msg_down = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_down, 0, {'timestamp': ts})

            self.control_socket.sendto(msg_ctrl, (self.server_addr, self.control_port))
            self.upload_socket.sendto(msg_up, (self.server_addr, self.upload_port))
            self.download_socket.sendto(msg_down, (self.server_addr, self.download_port))
            
            print("Client connected successfully")
            sys.stdout.flush()
            
            # Initialize heartbeat timing
            self.last_heartbeat = time.time()
            
            # Run main client communication loop
            self.client_comm_loop()
            
        except socket.timeout:
            print("Timeout waiting for server response", file=sys.stderr)
            self.running = False
        except Exception as e:
            print(f"Error connecting to server: {e}", file=sys.stderr)
            self.running = False
    
    def client_comm_loop(self):
        """Main client communication loop - handles heartbeat timing and responses"""
        # Set socket blocking based on configured block_time
        if self.block_time > 0:
            timeout = self.block_time / 1000  # Convert milliseconds to seconds
            self.main_socket.settimeout(timeout)
        else:
            self.main_socket.setblocking(False)
        
        # Send initial heartbeat
        self.send_heartbeat()
        
        while self.running:
            current_time = time.time()
            
            if current_time - self.last_heartbeat >= self.heartbeat_interval:
                self.send_heartbeat()
                self.last_heartbeat = current_time
            
            # No HEARTBEAT handling on main socket; heartbeats use per-port sockets only.

            # Check per-port sockets for heartbeat responses
            for sock, label, port in ((self.control_socket, 'CONTROL', self.control_port), (self.upload_socket, 'UPLOAD', self.upload_port), (self.download_socket, 'DOWNLOAD', self.download_port)):
                if not sock:
                    continue
                try:
                    data, _ = sock.recvfrom(4096)
                    #print(f"received {len(data)} bytes of packet data on {label} port")
                except socket.timeout:
                    continue
                except Exception:
                    continue

                try:
                    mt, data_channel, channel_seq, seq_offset, json_obj = MessagePacket.parse_packet(data)
                except Exception:
                    continue

                # Check if this is a heartbeat message (data_channel == heartbeat_key)
                if data_channel != self.heartbeat_key:
                    continue

                if mt == MessageType.HEARTBEAT_1:
                    client_timestamp = None
                    server_timestamp = None
                    if isinstance(json_obj, dict):
                        client_timestamp = json_obj.get('client_timestamp')
                        server_timestamp = json_obj.get('server_timestamp')

                    now = time.time()
                    if client_timestamp is not None:
                        latency = (now - client_timestamp) * 1000
                        print(f"Client latency {label:9}: {latency:.2f} ms", file=sys.stderr)
                        sys.stderr.flush()
                        try:
                            self.record_latency(label, latency)
                        except Exception:
                            pass

                    # Send final HEARTBEAT_2 to server main socket
                    resp_json = {'client_timestamp': client_timestamp, 'server_timestamp': server_timestamp}
                    resp_seq = self.get_and_increment_sequence(port, data_channel)
                    resp = MessagePacket.format_packet(MessageType.HEARTBEAT_2, data_channel, resp_seq, seq_offset, resp_json)
                    sock.sendto(resp, (self.server_addr, port))
    
    def send_heartbeat(self):
        """Send heartbeat with timestamp to server"""
        timestamp = time.time()
        json_obj = {'timestamp': timestamp}
        # Send heartbeats on per-port sockets using heartbeat_key in data_channel
        try:
            if self.control_socket and self.control_port:
                seq_ctrl = self.get_and_increment_sequence(self.control_port, self.heartbeat_key)
                message_ctrl = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_ctrl, 0, json_obj)
                self.control_socket.sendto(message_ctrl, (self.server_addr, self.control_port))
        except Exception:
            pass
        try:
            if self.upload_socket and self.upload_port:
                seq_up = self.get_and_increment_sequence(self.upload_port, self.heartbeat_key)
                message_up = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_up, 0, json_obj)
                self.upload_socket.sendto(message_up, (self.server_addr, self.upload_port))
        except Exception:
            pass
        try:
            if self.download_socket and self.download_port:
                seq_down = self.get_and_increment_sequence(self.download_port, self.heartbeat_key)
                message_down = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_down, 0, json_obj)
                self.download_socket.sendto(message_down, (self.server_addr, self.download_port))
        except Exception:
            pass
    
    def stop(self):
        """Stop the client"""
        self.running = False
        for sock in [self.main_socket, self.control_socket, self.upload_socket, self.download_socket]:
            if sock:
                sock.close()


def parse_addr_port(addr_port_str: str, default_addr: str = "0.0.0.0", 
                    default_port: int = 6711) -> Tuple[str, int]:
    """Parse address:port string, handling missing values"""
    if ':' in addr_port_str:
        parts = addr_port_str.split(':')
        addr = parts[0] if parts[0] else default_addr
        port = int(parts[1]) if parts[1] else default_port
    else:
        # If no colon, treat as address only
        addr = addr_port_str if addr_port_str else default_addr
        port = default_port
    
    return addr, port


def resolve_config_path(config_arg: Optional[str]) -> Path:
    """Resolve config path from argument - can be directory or full file path"""
    if config_arg is None:
        return Path.home() / '.wyndrvr' / 'config'
    
    config_path = Path(config_arg).expanduser().resolve()
    
    # If it's an existing directory, append 'config' filename
    if config_path.is_dir():
        config_path = config_path / 'config'
    # If it doesn't exist and has no extension, treat as config file name
    elif not config_path.exists() and not config_path.suffix:
        # Don't append 'config' if the name itself looks like a config file
        pass
    
    return config_path


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='wyndrvr - Latency and Bandwidth Utility'
    )
    parser.add_argument(
        '--server',
        nargs='?',
        const='',
        metavar='[addr]:[port]',
        help='Run in server mode with optional bind address and port'
    )
    parser.add_argument(
        '--config',
        metavar='path',
        help='Path to config file or directory (default: ~/.wyndrvr/config)'
    )
    parser.add_argument(
        '--create-config',
        action='store_true',
        help='Create a default config file'
    )
    parser.add_argument(
        '--bind-addr',
        metavar='addr',
        help='Server bind address (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--bind-port',
        type=int,
        metavar='port',
        help='Server bind port (default: 6711)'
    )
    parser.add_argument(
        '--port-ranges',
        metavar='ranges',
        help='Port ranges for clients (format: 7000-8000,9000-9500)'
    )
    parser.add_argument(
        '--connection-parallelibility',
        choices=['SINGLE', 'THREAD', 'PROCESS'],
        help='Connection parallelization mode'
    )
    parser.add_argument(
        '--port-parallelability',
        choices=['SINGLE', 'THREAD', 'PROCESS'],
        help='Port parallelization mode'
    )
    parser.add_argument(
        '--incoming-blocking-level',
        type=int,
        metavar='microseconds',
        help='Incoming blocking level in microseconds'
    )
    parser.add_argument(
        '--incoming-sleep',
        type=int,
        metavar='microseconds',
        help='Incoming sleep time in microseconds'
    )
    parser.add_argument(
        '--max-send-time',
        type=int,
        metavar='microseconds',
        help='Maximum send time in microseconds'
    )
    parser.add_argument(
        '--send-sleep',
        type=int,
        metavar='microseconds',
        help='Send sleep time in microseconds'
    )
    parser.add_argument(
        '--heartbeat-rate',
        type=int,
        metavar='milliseconds',
        help='Heartbeat rate in milliseconds (default: 5000)'
    )
    parser.add_argument(
        '--adjustment-delay',
        type=int,
        metavar='microseconds',
        help='Adjustment delay in microseconds'
    )
    parser.add_argument(
        '--flow-control-rate',
        type=int,
        metavar='rate',
        help='Flow control rate divider'
    )
    parser.add_argument(
        '--server-block-time',
        type=int,
        metavar='milliseconds',
        help='Server socket block time in milliseconds (default: 100)'
    )
    parser.add_argument(
        '--client-block-time',
        type=int,
        metavar='milliseconds',
        help='Client socket block time in milliseconds (default: 100)'
    )
    parser.add_argument(
        'client_target',
        nargs='?',
        metavar='[addr]:[port]',
        help='Server address and port for client mode'
    )
    
    args = parser.parse_args()
    
    # Resolve config path
    config_path = resolve_config_path(args.config)
    
    # Handle --create-config
    if args.create_config:
        server = WyndServer(ServerConfig())
        # Check if any config arguments were provided
        has_config_args = any([
            args.bind_addr, args.bind_port, args.port_ranges,
            args.connection_parallelibility, args.port_parallelability,
            args.incoming_blocking_level, args.incoming_sleep,
            args.max_send_time, args.send_sleep, args.heartbeat_rate,
            args.adjustment_delay, args.flow_control_rate,
            args.server_block_time, args.client_block_time
        ])
        
        if has_config_args:
            # Use update method to handle command line args
            if server.update_config_from_args(config_path, args):
                sys.exit(0)
            else:
                sys.exit(1)
        else:
            # Use default creation
            if server.create_default_config(config_path):
                sys.exit(0)
            else:
                sys.exit(1)
    
    # Determine mode
    # If no mode specified, default to client connecting to localhost:6711
    if args.server is None and not args.client_target:
        args.client_target = '127.0.0.1:6711'

    if args.server is not None:
        # Server mode
        config = ServerConfig()
        
        # Load config file if exists
        server = WyndServer(config)
        if config_path.exists():
            config = server.load_config(config_path)
        elif args.config:
            print(f"Warning: Config file not found: {config_path}", file=sys.stderr)
        
        # Override with command line arguments if provided
        if args.server:
            addr, port = parse_addr_port(args.server, config.bind_addr, config.bind_port)
            config.bind_addr = addr
            config.bind_port = port
        
        server.config = config
        
        try:
            server.start()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            server.stop()
            try:
                server.print_latency_summary()
            except Exception:
                pass
    
    elif args.client_target:
        # Client mode
        addr, port = parse_addr_port(args.client_target, default_port=6711)
        
        # Load config to get client_block_time if available
        block_time = 100  # default
        if config_path.exists():
            server = WyndServer(ServerConfig())
            config = server.load_config(config_path)
            block_time = config.client_block_time
        
        client = WyndClient(addr, port, block_time)
        # Set heartbeat interval from config if present (milliseconds -> seconds)
        try:
            client.heartbeat_interval = config.heartbeat_rate / 1000.0
        except Exception:
            pass
        
        try:
            client.start()
            # Keep client running
            while client.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down client...")
            client.stop()
            try:
                client.print_latency_summary()
            except Exception:
                pass
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
