#!/usr/bin/env python3
"""
wyndrvr - Latency and Bandwidth Utility
A UDP-based network testing tool for measuring latency and bandwidth.
"""

import argparse
import socket
import sys
import os
import threading
import multiprocessing
import time
import select
from pathlib import Path
from enum import Enum
from typing import Optional, Tuple, List
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
    heartbeat_rate: int = 1000000  # microseconds (1 second)
    adjustment_delay: int = 1000000  # microseconds (1 second)
    flow_control_rate: int = 10  # divider for adjustment_delay
    
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
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
        
        return config
    
    def start(self):
        """Start the server"""
        self.running = True
        
        # Create main socket
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.main_socket.bind((self.config.bind_addr, self.config.bind_port))
        
        # Set socket timeout based on incoming_blocking_level
        if self.config.incoming_blocking_level > 0:
            timeout = self.config.incoming_blocking_level / 1_000_000  # Convert to seconds
            self.main_socket.settimeout(timeout)
        else:
            self.main_socket.setblocking(False)
        
        print(f"Server started on {self.config.bind_addr}:{self.config.bind_port}")
        
        # Main server loop
        self.run_server_loop()
    
    def run_server_loop(self):
        """Main server communication loop"""
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
        """Handle new client connection"""
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
        
        # Send port information back to client
        ports = self.client_connections[client_addr]
        response = f"{ports[0]},{ports[1]},{ports[2]}".encode()
        self.main_socket.sendto(response, client_addr)
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.main_socket:
            self.main_socket.close()


class WyndClient:
    """UDP Client for wyndrvr"""
    
    def __init__(self, server_addr: str, server_port: int):
        self.server_addr = server_addr
        self.server_port = server_port
        self.main_socket = None
        self.control_socket = None
        self.upload_socket = None
        self.download_socket = None
        self.running = False
    
    def start(self):
        """Start the client and connect to server"""
        self.running = True
        
        # Create main socket
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        print(f"Connecting to server {self.server_addr}:{self.server_port}")
        
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
            
        except socket.timeout:
            print("Timeout waiting for server response", file=sys.stderr)
        except Exception as e:
            print(f"Error connecting to server: {e}", file=sys.stderr)
    
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
        'client_target',
        nargs='?',
        metavar='[addr]:[port]',
        help='Server address and port for client mode'
    )
    
    args = parser.parse_args()
    
    # Determine mode
    if args.server is not None:
        # Server mode
        config_path = Path.home() / '.wyndrvr' / 'config'
        config = ServerConfig()
        
        # Load config file if exists
        server = WyndServer(config)
        if config_path.exists():
            config = server.load_config(config_path)
        
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
        
        client = WyndClient(addr, port)
        
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
