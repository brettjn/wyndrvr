#!/usr/bin/env python3
"""
wyndrvr - Latency and Bandwidth Utility
A UDP-based network testing tool for measuring latency and bandwidth.
"""

__version__ = "0.4"
__version_notes__ = """
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
from pathlib import Path
from enum import Enum
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass


class ParallelMode(Enum):
    """Parallelization modes for server operations"""
    SINGLE = "SINGLE"
    THREAD = "THREAD"
    PROCESS = "PROCESS"


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
                        if len(available_ports) == count:
                            break
                if len(available_ports) == count:
                    break
            
            if len(available_ports) < count:
                return None
            
            for port in available_ports:
                self.used_ports.add(port)
            
            return available_ports
    
    def release_ports(self, ports: List[int]):
        """Release previously allocated ports"""
        with self.lock:
            for port in ports:
                self.used_ports.discard(port)


class WyndServer:
    """UDP Server for wyndrvr"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.port_manager = PortManager(config.port_ranges)
        self.running = False
        self.main_socket = None
        self.client_connections = {}  # client_addr -> (control_port, upload_port, download_port)
        self.client_sockets = {}  # port -> socket for client connections
    
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
        
        # Update with command line arguments
        if args.bind_addr is not None:
            old_val = config_dict.get('bind_addr')
            config_dict['bind_addr'] = args.bind_addr
            if not is_new and old_val != args.bind_addr:
                changes.append(f"bind_addr: {old_val} -> {args.bind_addr}")
        
        if args.bind_port is not None:
            old_val = config_dict.get('bind_port')
            config_dict['bind_port'] = str(args.bind_port)
            if not is_new and old_val != str(args.bind_port):
                changes.append(f"bind_port: {old_val} -> {args.bind_port}")
        
        if args.port_ranges is not None:
            old_val = config_dict.get('port_ranges')
            config_dict['port_ranges'] = args.port_ranges
            if not is_new and old_val != args.port_ranges:
                changes.append(f"port_ranges: {old_val} -> {args.port_ranges}")
        
        if args.connection_parallelibility is not None:
            old_val = config_dict.get('connection_parallelibility')
            config_dict['connection_parallelibility'] = args.connection_parallelibility
            if not is_new and old_val != args.connection_parallelibility:
                changes.append(f"connection_parallelibility: {old_val} -> {args.connection_parallelibility}")
        
        if args.port_parallelability is not None:
            old_val = config_dict.get('port_parallelability')
            config_dict['port_parallelability'] = args.port_parallelability
            if not is_new and old_val != args.port_parallelability:
                changes.append(f"port_parallelability: {old_val} -> {args.port_parallelability}")
        
        if args.incoming_blocking_level is not None:
            old_val = config_dict.get('incoming_blocking_level')
            config_dict['incoming_blocking_level'] = str(args.incoming_blocking_level)
            if not is_new and old_val != str(args.incoming_blocking_level):
                changes.append(f"incoming_blocking_level: {old_val} -> {args.incoming_blocking_level}")
        
        if args.incoming_sleep is not None:
            old_val = config_dict.get('incoming_sleep')
            config_dict['incoming_sleep'] = str(args.incoming_sleep)
            if not is_new and old_val != str(args.incoming_sleep):
                changes.append(f"incoming_sleep: {old_val} -> {args.incoming_sleep}")
        
        if args.max_send_time is not None:
            old_val = config_dict.get('max_send_time')
            config_dict['max_send_time'] = str(args.max_send_time)
            if not is_new and old_val != str(args.max_send_time):
                changes.append(f"max_send_time: {old_val} -> {args.max_send_time}")
        
        if args.send_sleep is not None:
            old_val = config_dict.get('send_sleep')
            config_dict['send_sleep'] = str(args.send_sleep)
            if not is_new and old_val != str(args.send_sleep):
                changes.append(f"send_sleep: {old_val} -> {args.send_sleep}")
        
        if args.heartbeat_rate is not None:
            old_val = config_dict.get('heartbeat_rate')
            config_dict['heartbeat_rate'] = str(args.heartbeat_rate)
            if not is_new and old_val != str(args.heartbeat_rate):
                changes.append(f"heartbeat_rate: {old_val} -> {args.heartbeat_rate}")
        
        if args.adjustment_delay is not None:
            old_val = config_dict.get('adjustment_delay')
            config_dict['adjustment_delay'] = str(args.adjustment_delay)
            if not is_new and old_val != str(args.adjustment_delay):
                changes.append(f"adjustment_delay: {old_val} -> {args.adjustment_delay}")
        
        if args.flow_control_rate is not None:
            old_val = config_dict.get('flow_control_rate')
            config_dict['flow_control_rate'] = str(args.flow_control_rate)
            if not is_new and old_val != str(args.flow_control_rate):
                changes.append(f"flow_control_rate: {old_val} -> {args.flow_control_rate}")
        
        if args.server_block_time is not None:
            old_val = config_dict.get('server_block_time')
            config_dict['server_block_time'] = str(args.server_block_time)
            if not is_new and old_val != str(args.server_block_time):
                changes.append(f"server_block_time: {old_val} -> {args.server_block_time}")
        
        if args.client_block_time is not None:
            old_val = config_dict.get('client_block_time')
            config_dict['client_block_time'] = str(args.client_block_time)
            if not is_new and old_val != str(args.client_block_time):
                changes.append(f"client_block_time: {old_val} -> {args.client_block_time}")
        
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
                # Receive incoming packets
                data, client_addr = self.main_socket.recvfrom(4096)
                self.handle_client_connection(client_addr, data)
            except socket.timeout:
                pass
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"Error in server loop: {e}", file=sys.stderr)
            
            # Sleep if configured
            if self.config.incoming_sleep > 0:
                time.sleep(self.config.incoming_sleep / 1_000_000)
    
    def handle_client_connection(self, client_addr: Tuple[str, int], data: bytes):
        """Handle new client connection and heartbeat messages"""
        # Check if this is a heartbeat message
        if data.startswith(b"HEARTBEAT:"):
            # Extract timestamp and echo back with server timestamp
            client_timestamp = struct.unpack('d', data[10:])[0]
            server_time = time.time()
            
            # Calculate server-side latency (half round-trip from previous exchange)
            response = b"HEARTBEAT_ECHO:" + struct.pack('dd', client_timestamp, server_time)
            self.main_socket.sendto(response, client_addr)
            return
        
        if data.startswith(b"HEARTBEAT_FINAL:"):
            # Final echo from client - calculate latency
            client_timestamp, server_timestamp = struct.unpack('dd', data[16:])
            current_time = time.time()
            latency = (current_time - server_timestamp) * 1000  # Convert to milliseconds
            print(f"Server latency to {client_addr[0]}:{client_addr[1]}: {latency:.2f} ms", file=sys.stderr)
            sys.stderr.flush()
            return
        
        if client_addr not in self.client_connections:
            # Allocate three ports for this client
            ports = self.port_manager.allocate_ports(3)
            
            if ports is None:
                print(f"Failed to allocate ports for client {client_addr}", file=sys.stderr)
                return
            
            control_port, upload_port, download_port = ports
            self.client_connections[client_addr] = (control_port, upload_port, download_port)
            
            print(f"Client connected: {client_addr[0]}:{client_addr[1]}")
            print(f"  Control Port: {control_port}")
            print(f"  Upload Port: {upload_port}")
            print(f"  Download Port: {download_port}")
            sys.stdout.flush()
            
            # Create sockets for this client's ports
            self.setup_client_sockets(control_port, upload_port, download_port)
        
        # Send port information back to client
        ports = self.client_connections[client_addr]
        response = f"{ports[0]},{ports[1]},{ports[2]}".encode()
        self.main_socket.sendto(response, client_addr)
    
    def setup_client_sockets(self, control_port: int, upload_port: int, download_port: int):
        """Setup sockets for client ports"""
        for port in [control_port, upload_port, download_port]:
            if port not in self.client_sockets:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind((self.config.bind_addr, port))
                sock.setblocking(False)
                self.client_sockets[port] = sock
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.main_socket:
            self.main_socket.close()
        for sock in self.client_sockets.values():
            sock.close()


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
            data, _ = self.main_socket.recvfrom(4096)
            ports_str = data.decode()
            control_port, upload_port, download_port = map(int, ports_str.split(','))
            
            print(f"Received port assignment:")
            print(f"  Control Port: {control_port}")
            print(f"  Upload Port: {upload_port}")
            print(f"  Download Port: {download_port}")
            
            # Create sockets for each port
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.upload_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.download_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Send heartbeat to each port
            self.control_socket.sendto(b"HEARTBEAT", (self.server_addr, control_port))
            self.upload_socket.sendto(b"HEARTBEAT", (self.server_addr, upload_port))
            self.download_socket.sendto(b"HEARTBEAT", (self.server_addr, download_port))
            
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
            
            # Check for heartbeat responses (blocks up to 0.1 seconds)
            try:
                data, _ = self.main_socket.recvfrom(4096)
                if data.startswith(b"HEARTBEAT_ECHO:") and len(data) >= 31:
                    client_timestamp, server_timestamp = struct.unpack('dd', data[15:])
                    current_time = time.time()
                    
                    # Calculate round-trip latency
                    latency = (current_time - client_timestamp) * 1000  # milliseconds
                    print(f"Client latency: {latency:.2f} ms", file=sys.stderr)
                    sys.stderr.flush()
                    
                    # Send final echo back to server
                    final_echo = b"HEARTBEAT_FINAL:" + struct.pack('dd', client_timestamp, server_timestamp)
                    self.main_socket.sendto(final_echo, (self.server_addr, self.server_port))
            except socket.timeout:
                pass
            except Exception as e:
                print(f"Error in client comm loop: {e}", file=sys.stderr)
    
    def send_heartbeat(self):
        """Send heartbeat with timestamp to server"""
        timestamp = time.time()
        message = b"HEARTBEAT:" + struct.pack('d', timestamp)
        self.main_socket.sendto(message, (self.server_addr, self.server_port))
    
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
        
        try:
            client.start()
            # Keep client running
            while client.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down client...")
            client.stop()
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
