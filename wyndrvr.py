#!/usr/bin/env python3
"""
wyndrvr - Latency and Bandwidth Utility
A UDP-based network testing tool for measuring latency and bandwidth.
"""


__version__ = "0.12"
__version_notes__ = """
Version 0.12:
- Fixed duplicate sequence number transmission bug in client bandwidth test
- Added span merging logic after detecting dropped packets in FLOW_CONTROL handler
- Prevents duplicate (begin, end) tuples in working_sequence_span that caused same sequences to be sent repeatedly
- Merging algorithm sorts spans and combines overlapping/adjacent ranges (begin <= previous_end + 1)
- Ensures get_lowest() returns unique sequence numbers for proper bandwidth test operation

Version 0.11:
- Added TEST_RESULT message type (MessageType.TEST_RESULT = 7)
- Server tracks bytes received and retransmit count during bandwidth tests
- After 30 seconds, server sends TEST_RESULT with upload statistics to client
- TEST_RESULT includes: bandwidth (bps), bytes received, retransmit count, duration
- Client acknowledges TEST_RESULT and continues acking for 5 seconds
- Client prints upload statistics and shuts down after 5 seconds
- Server closes client connection after receiving TEST_RESULT ack
- Uses GUID-based acknowledgment protocol with 100ms retransmission intervals
- Fixed hang when circular buffer becomes full in FLOW_CONTROL processing
- Changed dropped packet detection to work with span ranges instead of iterating individual sequences
- Prevents attempting to iterate through billions of sequence numbers in large spans
- Improves performance and reliability when dealing with dropped packets during bandwidth tests

Version 0.9:
- Added --test-drop-rate option to simulate packet loss (default: 0)
- test_drop_rate value is probability (0.0-1.0) that a packet will be dropped
- When test_drop_rate > 0, random number generated before each sendto call
- If random() < test_drop_rate, packet is not sent (simulating network loss)
- Applies to all packet types: heartbeats, control, bandwidth test, flow control
- Useful for testing protocol reliability and retransmission logic
- Added --test-delay option with configurable delay in communication loops (default: 100ms if flag used, 0 if not)
- Added --version argument to print version number
- Added verbose logging for BANDWIDTH_TEST packet sends/receives when using --test-verbose

Version 0.8:
- Implemented BANDWIDTH_TEST packet generation and sending
- Added SequenceSpan.get_lowest() method to retrieve and remove lowest sequence number
- Client continuously sends BANDWIDTH_TEST packets during 30-second upload test
- Packets sent at ~10 per iteration without blocking other communication
- Added bw_packet_length configuration parameter (default 900 bytes)
- BANDWIDTH_TEST packets include dummy_data payload of configurable length
- Dummy data consists of alphabet, numbers, and ASCII symbols repeated to target length
- Automatic test timeout after 30 seconds with cleanup
- Non-blocking design maintains heartbeat and control message responsiveness
- Unit tests for SequenceSpan.get_lowest() and packet format validation

Version 0.7:
- Added --bwup flag to initiate upload bandwidth test (30 seconds)
- Added --test-verbose flag to enable debug output for control/flow messages
- Implemented BWUP command with UploadControlMessage acknowledgment system
- Added UploadDataSink class with SequenceSpan for tracking sequence ranges
- Server automatically starts/stops bandwidth test mode with 30-second timeout
- FLOW_CONTROL packets sent every second (adjustment_delay/flow_control_rate)
- Added MessagePacket.format_binary_packet for binary payloads
- Changed adjustment_delay from microseconds to milliseconds in config
- Added ucm_delay config setting (default 100ms) for control message retransmission
- Client automatically resends BWUP if not acknowledged within ucm_delay
- Client decodes FLOW_CONTROL packets and stores SequenceSpans in circular buffer

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
import random
import uuid
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
    HEARTBEAT_0    = 0
    HEARTBEAT_1    = 1
    HEARTBEAT_2    = 2
    FLOW_CONTROL   = 3
    BANDWIDTH_TEST = 4
    DATA           = 5
    CONTROL        = 6
    TEST_RESULT    = 7


class PortType(Enum):
    """Port types for client connections"""
    CONTROL = "control"
    UPLOAD = "upload"
    DOWNLOAD = "download"


class UDS_Type(Enum):
    """Upload Data Sink types"""
    BANDWIDTH = 0


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
        
        packet = header + body
        if len(packet) > 1400:
            raise ValueError(f'Packet exceeds maximum size of 1400 bytes: {len(packet)} bytes')
        
        return packet

    @classmethod
    def format_binary_packet(cls, msg_type, data_channel: int, channel_sequence_number: int, sequence_offset: int, binary_data: bytes) -> bytes:
        """Format packet with binary data payload instead of JSON"""
        mt = int(msg_type.value) if isinstance(msg_type, MessageType) else int(msg_type)
        # 1 byte message type
        header = bytes([mt])
        # 3 bytes data_channel
        header += int(data_channel).to_bytes(3, 'big')
        # 8 bytes channel_sequence_number
        header += struct.pack('>Q', int(channel_sequence_number))
        # 8 bytes sequence_offset
        header += struct.pack('>Q', int(sequence_offset))
        
        packet = header + binary_data
        if len(packet) > 1400:
            raise ValueError(f'Packet exceeds maximum size of 1400 bytes: {len(packet)} bytes')
        
        return packet

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


class UploadControlMessage:
    """Represents an upload control message with unique identifier"""
    
    def __init__(self, params: Dict):
        """Initialize with dictionary of key-value pairs and add unique identifier"""
        self.uid = str(uuid.uuid4())
        self.params = dict(params)
        self.params['uid'] = self.uid
        self.last_sent = 0.0  # Timestamp of last send
    
    def get_uid(self) -> str:
        """Return the unique identifier"""
        return self.uid
    
    def get_params(self) -> Dict:
        """Return the parameters dictionary including uid"""
        return self.params
    
    def should_delete(self) -> bool:
        """Check if this message should be deleted (ack=0)"""
        return self.params.get('ack', 1) == 0


class SequenceSpan:
    """Represents a list of sequence number spans (beginning and ending pairs)"""
    
    def __init__(self, spans: Optional[List[Tuple[int, int]]] = None):
        """Initialize with list of (begin, end) tuples or default to full 8-byte span
        
        Spans are automatically sorted by their begin value to ensure lowest sequences
        are at the front of the list.
        """
        if spans is None:
            # Default to complete 8-byte span: 0 to 2^64 - 1
            self.spans = [(0, (2**64) - 1)]
        else:
            # Sort spans by begin value to maintain numerical order
            self.spans = sorted(spans, key=lambda x: x[0])
    
    def get_spans(self) -> List[Tuple[int, int]]:
        """Return the list of spans"""
        return self.spans
    
    def to_binary(self) -> bytes:
        """Convert spans to binary representation"""
        # Each span is two 8-byte unsigned integers (begin, end)
        # Format: number of spans (4 bytes) followed by span pairs
        result = struct.pack('>I', len(self.spans))  # 4-byte unsigned int for count
        for begin, end in self.spans:
            result += struct.pack('>QQ', begin, end)  # Two 8-byte unsigned long longs
        return result
    
    @classmethod
    def from_binary(cls, binary_data: bytes) -> 'SequenceSpan':
        """Create SequenceSpan from binary representation"""
        if len(binary_data) < 4:
            raise ValueError('Binary data too short for SequenceSpan')
        
        # Read span count (4 bytes)
        span_count = struct.unpack('>I', binary_data[0:4])[0]
        
        # Each span is 16 bytes (two 8-byte unsigned long longs)
        expected_len = 4 + (span_count * 16)
        if len(binary_data) < expected_len:
            raise ValueError(f'Binary data too short: expected {expected_len}, got {len(binary_data)}')
        
        spans = []
        offset = 4
        for i in range(span_count):
            begin, end = struct.unpack('>QQ', binary_data[offset:offset+16])
            spans.append((begin, end))
            offset += 16
        
        return cls(spans)
    
    def get_lowest(self) -> Optional[int]:
        """Get and remove the lowest sequence number from spans"""
        if not self.spans or len(self.spans) == 0:
            return None
        
        # Find the span with the lowest begin value
        min_idx = 0
        min_begin = self.spans[0][0]
        for i in range(1, len(self.spans)):
            if self.spans[i][0] < min_begin:
                min_begin = self.spans[i][0]
                min_idx = i
        
        # Get the lowest value
        begin, end = self.spans[min_idx]
        lowest = begin
        
        # Update the span
        if begin == end:
            # Remove this span entirely
            self.spans.pop(min_idx)
        else:
            # Increment the begin value
            self.spans[min_idx] = (begin + 1, end)
        
        return lowest
    
    def remove_seq(self, seq_num: int) -> bool:
        """Remove a specific sequence number from the spans
        
        If the sequence number is in the middle of a span, split it into two spans.
        For example, removing 8 from span (5, 100) results in spans (5, 7) and (9, 100).
        
        Args:
            seq_num: The sequence number to remove
            
        Returns:
            True if the sequence number was found and removed, False otherwise
        """
        # Find which span contains this sequence number
        for i, (begin, end) in enumerate(self.spans):
            if begin <= seq_num <= end:
                # Found the span containing this sequence number
                
                if begin == end:
                    # Span contains only this one number, remove the entire span
                    self.spans.pop(i)
                elif seq_num == begin:
                    # Removing from the beginning, just increment begin
                    self.spans[i] = (begin + 1, end)
                elif seq_num == end:
                    # Removing from the end, just decrement end
                    self.spans[i] = (begin, end - 1)
                else:
                    # Removing from the middle, split into two spans
                    # First span: from begin to seq_num-1
                    # Second span: from seq_num+1 to end
                    self.spans[i] = (begin, seq_num - 1)
                    self.spans.insert(i + 1, (seq_num + 1, end))
                
                return True
        
        # Sequence number not found in any span
        return False


class UploadDataSink:
    """Represents an upload data sink for bandwidth testing"""
    
    def __init__(self, uds_type: UDS_Type, channel: int):
        """Initialize with type and channel"""
        self.uds_type = uds_type
        self.channel = channel
        self.created_at = time.time()
        self.sequence_span = None
        self.last_flow_control_sent = 0.0  # Timestamp of last FLOW_CONTROL send
        self.bytes_received = 0  # Total bytes received on this channel
        self.retransmit_count = 0  # Count of retransmitted packets (sequence_offset > 0)
        
        # For BANDWIDTH type, create a SequenceSpan with default 8-byte span
        if uds_type == UDS_Type.BANDWIDTH:
            self.sequence_span = SequenceSpan()
    
    def get_type(self) -> UDS_Type:
        """Return the type"""
        return self.uds_type
    
    def get_channel(self) -> int:
        """Return the channel"""
        return self.channel


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
    adjustment_delay: int = 1000  # milliseconds (1 second)
    flow_control_rate: int = 10  # divider for adjustment_delay
    server_block_time: int = 100  # milliseconds
    client_block_time: int = 100  # milliseconds
    ucm_delay: int = 100  # milliseconds (upload control message delay)
    test_verbose: bool = False  # Print test/debug messages
    bw_packet_length: int = 900  # bytes (bandwidth test packet payload length)
    test_delay: int = 0  # milliseconds (delay in communication loops for testing)
    test_drop_rate: float = 0.0  # probability (0.0-1.0) of dropping packets for testing
    
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
        # Upload control messages dictionary: uid -> UploadControlMessage instance
        self.upload_control_messages: Dict[str, UploadControlMessage] = {}
        # Upload data sinks dictionary: channel -> UploadDataSink instance
        self.upload_data_sinks: Dict[int, UploadDataSink] = {}
        # Upload bandwidth test start timestamp (None when not in test mode)
        self.upload_bandwidth_started: Optional[float] = None
        # Client socket addresses (where to send replies)
        self.control_client_addr = None
        self.upload_client_addr = None
        self.download_client_addr = None
        # Test verbose flag
        self.test_verbose = server_ref.config.test_verbose if server_ref else False
        
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
    
    def should_drop_packet(self) -> bool:
        """Check if packet should be dropped based on test_drop_rate"""
        if self.server and self.server.config.test_drop_rate > 0:
            return random.random() < self.server.config.test_drop_rate
        return False

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
        
        # Store the source address for replies on each port type
        if src_addr:
            if port_type == PortType.CONTROL:
                self.control_client_addr = src_addr
            elif port_type == PortType.UPLOAD:
                self.upload_client_addr = src_addr
            elif port_type == PortType.DOWNLOAD:
                self.download_client_addr = src_addr
        
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
                            if not self.should_drop_packet():
                                self.control_socket.sendto(resp, src_addr)
                        except Exception:
                            pass
                    elif port_type == PortType.UPLOAD and self.upload_socket:
                        try:
                            if not self.should_drop_packet():
                                self.upload_socket.sendto(resp, src_addr)
                        except Exception:
                            pass
                    elif port_type == PortType.DOWNLOAD and self.download_socket:
                        try:
                            if not self.should_drop_packet():
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

        # Handle CONTROL messages
        if mt == MessageType.CONTROL and port_type == PortType.CONTROL:
            if isinstance(json_obj, dict):
                cmd = json_obj.get('cmd')
                if cmd == 'BWUP':
                    # Create UploadControlMessage with ack=0 and the channel from the request
                    channel_from_client = json_obj.get('channel', data_channel)
                    ucm = UploadControlMessage({'cmd': 'BWUP', 'ack': 0, 'channel': channel_from_client})
                    uid = ucm.get_uid()
                    self.upload_control_messages[uid] = ucm
                    if self.test_verbose:
                        print(f"Server received BWUP packet from {self.client_addr[0]}:{self.client_addr[1]} on channel {channel_from_client}, created UCM {uid}", file=sys.stderr)
                        sys.stderr.flush()
        
        # Handle TEST_RESULT messages (ack from client)
        if mt == MessageType.TEST_RESULT and port_type == PortType.CONTROL:
            if isinstance(json_obj, dict):
                guid = json_obj.get('guid')
                ack = json_obj.get('ack')
                if guid and ack == 0:
                    # Client is acknowledging our TEST_RESULT, remove UCM and close connection
                    uid_to_remove = None
                    for uid, ucm in self.upload_control_messages.items():
                        if ucm.get_params().get('guid') == guid:
                            uid_to_remove = uid
                            break
                    
                    if uid_to_remove:
                        del self.upload_control_messages[uid_to_remove]
                        if self.test_verbose:
                            print(f"Server received TEST_RESULT ack from client for guid {guid}, closing connection", file=sys.stderr)
                            sys.stderr.flush()
                        
                        # Close the connection
                        self.close()
                        # Mark this client for removal from server's client_connections
                        if self.server:
                            self.server.mark_client_for_removal(self.client_addr)
        
        # Handle BANDWIDTH_TEST messages (upload bandwidth test data)
        if mt == MessageType.BANDWIDTH_TEST and port_type == PortType.UPLOAD:
            # Check if we have an active upload data sink for this channel
            if data_channel in self.upload_data_sinks:
                # Calculate the actual sequence number (channel_sequence_number - sequence_offset)
                actual_seq_num = channel_sequence_number - sequence_offset
                
                # Remove the actual sequence number from the sequence span
                sink = self.upload_data_sinks[data_channel]
                if sink.sequence_span:
                    sink.sequence_span.remove_seq(actual_seq_num)
                
                # Track bytes received (entire packet length)
                sink.bytes_received += len(data)
                
                # Track retransmissions (sequence_offset is the total retransmit count)
                sink.retransmit_count = sequence_offset
                
                if self.test_verbose:
                    if sequence_offset != 0:
                        print(f"Server received BANDWIDTH_TEST packet channel_seq={channel_sequence_number}, actual_seq={actual_seq_num}, offset={sequence_offset} from {self.client_addr[0]}:{self.client_addr[1]} on channel {data_channel}", file=sys.stderr)
                    else:
                        print(f"Server received BANDWIDTH_TEST packet seq={channel_sequence_number} from {self.client_addr[0]}:{self.client_addr[1]} on channel {data_channel}", file=sys.stderr)
                    sys.stderr.flush()

        return True
    
    def send_upload_control_messages(self):
        """Send/resend upload control messages and delete those with ack=0"""
        current_time = time.time()
        to_delete = []
        
        # Need to know where to send - use stored control client address
        if not self.control_client_addr:
            return  # Don't send if we don't know where to send to
        
        for uid, ucm in list(self.upload_control_messages.items()):
            # Send the message on control port
            try:
                params = ucm.get_params()
                # Use a channel number from the params or generate one
                channel = params.get('channel', 1)
                seq = self.get_and_increment_sequence(self.control_port, channel)
                
                # Determine message type based on command
                cmd = params.get('cmd')
                if cmd == 'TEST_RESULT':
                    msg_type = MessageType.TEST_RESULT
                else:
                    msg_type = MessageType.CONTROL
                
                message = MessagePacket.format_packet(msg_type, channel, seq, 0, params)
                if not self.should_drop_packet():
                    self.control_socket.sendto(message, self.control_client_addr)
                ucm.last_sent = current_time
                if self.test_verbose:
                    print(f"Server sent UCM {uid} to {self.control_client_addr[0]}:{self.control_client_addr[1]}: {params}", file=sys.stderr)
                    sys.stderr.flush()
                
                # Check if this is the first BWUP ack being sent
                cmd = params.get('cmd')
                if cmd == 'BWUP' and params.get('ack') == 0 and self.upload_bandwidth_started is None:
                    # Start upload bandwidth test mode
                    self.upload_bandwidth_started = current_time
                    # Create UploadDataSink with BANDWIDTH type and the channel
                    uds = UploadDataSink(UDS_Type.BANDWIDTH, channel)
                    self.upload_data_sinks[channel] = uds
                    if self.test_verbose:
                        print(f"Server started upload bandwidth test on channel {channel}", file=sys.stderr)
                        sys.stderr.flush()
                
                # Check if should be deleted (ack=0)
                if ucm.should_delete():
                    to_delete.append(uid)
            except Exception as e:
                if self.test_verbose:
                    print(f"Error sending UCM {uid}: {e}", file=sys.stderr)
                    sys.stderr.flush()
        
        # Delete messages that were sent with ack=0
        for uid in to_delete:
            del self.upload_control_messages[uid]
            if self.test_verbose:
                print(f"Server deleted UCM {uid} (ack=0)", file=sys.stderr)
                sys.stderr.flush()
    
    def check_upload_bandwidth_timeout(self):
        """Check if upload bandwidth test has timed out (30 seconds) and clean up if needed"""
        if self.upload_bandwidth_started is not None:
            current_time = time.time()
            elapsed = current_time - self.upload_bandwidth_started
            
            if elapsed >= 30.0:  # 30 seconds
                # Calculate statistics and send TEST_RESULT for each sink
                for channel, sink in list(self.upload_data_sinks.items()):
                    # Calculate upload bandwidth in bits per second
                    duration = current_time - sink.created_at
                    if duration > 0:
                        bandwidth_bps = (sink.bytes_received * 8) / duration
                    else:
                        bandwidth_bps = 0
                    
                    # Create TEST_RESULT UploadControlMessage with statistics
                    import uuid
                    guid = str(uuid.uuid4())
                    params = {
                        'cmd': 'TEST_RESULT',
                        'ack': 1,
                        'guid': guid,
                        'channel': channel,
                        'bytes_received': sink.bytes_received,
                        'bandwidth_bps': bandwidth_bps,
                        'retransmit_count': sink.retransmit_count,
                        'duration': duration
                    }
                    
                    ucm = UploadControlMessage(params)
                    uid = ucm.get_uid()
                    self.upload_control_messages[uid] = ucm
                    
                    if self.test_verbose:
                        print(f"Server created TEST_RESULT for channel {channel}: {bandwidth_bps:.2f} bps, {sink.bytes_received} bytes, {sink.retransmit_count} retransmits", file=sys.stderr)
                        sys.stderr.flush()
                
                # Exit upload bandwidth test mode
                self.upload_bandwidth_started = None
                
                # Remove all UploadDataSink instances
                channels_to_remove = list(self.upload_data_sinks.keys())
                for channel in channels_to_remove:
                    del self.upload_data_sinks[channel]
                    if self.test_verbose:
                        print(f"Server stopped upload bandwidth test on channel {channel} (30 second timeout)", file=sys.stderr)
                        sys.stderr.flush()
    
    def send_flow_control_messages(self):
        """Send FLOW_CONTROL messages for all active upload data sinks"""
        if not self.upload_client_addr:
            return  # Don't send if we don't know where to send to
        
        current_time = time.time()
        
        for channel, sink in self.upload_data_sinks.items():
            # Calculate time since last send in milliseconds
            time_since_last = (current_time - sink.last_flow_control_sent) * 1000
            
            # Calculate resend interval from config: adjustment_delay / flow_control_rate
            # adjustment_delay is in milliseconds in config
            if self.server and self.server.config:
                resend_interval_ms = self.server.config.adjustment_delay / self.server.config.flow_control_rate
            else:
                resend_interval_ms = 1000.0  # Default to 1 second
            
            # Send if enough time has passed
            if time_since_last >= resend_interval_ms:
                try:
                    # Get binary representation of sequence spans, limiting to 1380 bytes
                    if sink.sequence_span:
                        # Each span is 16 bytes, plus 4 bytes for count
                        # Max 1380 bytes: (1380 - 4) / 16 = 86 spans
                        max_spans = 86
                        spans_to_send = sink.sequence_span.spans[:max_spans]
                        limited_span = SequenceSpan(spans_to_send)
                        binary_data = limited_span.to_binary()
                    else:
                        binary_data = b''
                    
                    # Create FLOW_CONTROL message with binary data
                    seq = self.get_and_increment_sequence(self.upload_port, channel)
                    message = MessagePacket.format_binary_packet(MessageType.FLOW_CONTROL, channel, seq, 0, binary_data)
                    if not self.should_drop_packet():
                        self.upload_socket.sendto(message, self.upload_client_addr)
                    sink.last_flow_control_sent = current_time
                    
                    if self.test_verbose:
                        print(f"Server sent FLOW_CONTROL on channel {channel} to {self.upload_client_addr[0]}:{self.upload_client_addr[1]}", file=sys.stderr)
                        sys.stderr.flush()
                except Exception as e:
                    if self.test_verbose:
                        print(f"Error sending FLOW_CONTROL on channel {channel}: {e}", file=sys.stderr)
                        sys.stderr.flush()
    
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
        self.clients_to_remove = []  # List of client addresses to remove

    def print_latency_summary(self):
        """Print latency summary for all clients"""
        print("\nServer latency summary by client:")
        if not self.client_connections:
            print("  No client connections")
            return
        for client_addr, client_comms in self.client_connections.items():
            client_comms.print_latency_summary()
    
    def mark_client_for_removal(self, client_addr: Tuple[str, int]):
        """Mark a client for removal from connections"""
        if client_addr not in self.clients_to_remove:
            self.clients_to_remove.append(client_addr)
    
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
                        elif key == 'ucm_delay':
                            config.ucm_delay = int(value)
                        elif key == 'test_verbose':
                            config.test_verbose = value.lower() in ('true', '1', 'yes')
                        elif key == 'bw_packet_length':
                            config.bw_packet_length = int(value)
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

# Heartbeat ms
heartbeat_rate=5000

# Flow control ms
adjustment_delay=3000  # three seconds
flow_control_rate=3

# Socket blocking times (milliseconds)
server_block_time=10
client_block_time=10

# Upload control message delay (milliseconds)
ucm_delay=100

# Bandwidth test packet length (bytes)
bw_packet_length=900
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
                'adjustment_delay': '1000',
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
                f.write(f"adjustment_delay={config_dict.get('adjustment_delay', '1000')}\n")
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
                        if self.config.test_drop_rate == 0 or random.random() >= self.config.test_drop_rate:
                            self.main_socket.sendto(response, client_addr)
                #else:
                #    # Try parsing as our binary MessagePacket (heartbeat, etc.)
                #    try:
                #        mt, data_channel, channel_seq, seq_offset, json_obj = MessagePacket.parse_packet(data)
                #        # Only handle heartbeat types here
                #        if isinstance(mt, MessageType) and mt in (MessageType.HEARTBEAT_0, MessageType.HEARTBEAT_1, MessageType.HEARTBEAT_2):
                #            self.handle_heartbeat_message(client_addr, data)
                #    except Exception:
                #        # Not a MessagePacket - ignore or handled elsewhere
                #        pass
                        
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
                
                # Send/resend upload control messages if any exist
                if client_comms.upload_control_messages:
                    client_comms.send_upload_control_messages()
                
                # Send FLOW_CONTROL messages for active upload data sinks
                if client_comms.upload_data_sinks:
                    client_comms.send_flow_control_messages()
                
                # Check if upload bandwidth test has timed out
                client_comms.check_upload_bandwidth_timeout()
            
            # Remove any clients marked for removal
            for client_addr in self.clients_to_remove:
                if client_addr in self.client_connections:
                    del self.client_connections[client_addr]
                    if self.config.test_verbose:
                        print(f"Server removed client {client_addr[0]}:{client_addr[1]} from connections", file=sys.stderr)
                        sys.stderr.flush()
            self.clients_to_remove.clear()
            
            # Test delay if configured
            if self.config.test_delay > 0:
                time.sleep(self.config.test_delay / 1000.0)
            
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
                if self.config.test_drop_rate == 0 or random.random() >= self.config.test_drop_rate:
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
    
    def __init__(self, server_addr: str, server_port: int, block_time: int = 100, bwup: bool = False, test_verbose: bool = False, test_delay: int = 0, test_drop_rate: float = 0.0):
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
        self.bwup = bwup  # Upload bandwidth test flag
        self.bwup_channel = None  # Channel number for BWUP test
        self.bwup_last_sent = 0.0  # Timestamp of last BWUP send
        self.bwup_acked = False  # Whether BWUP has been acknowledged
        self.ucm_delay = 100  # milliseconds (will be loaded from config if available)
        self.test_verbose = test_verbose  # Print test/debug messages
        self.test_delay = test_delay  # milliseconds (delay in communication loop)
        self.test_drop_rate = test_drop_rate  # probability (0.0-1.0) of dropping packets
        self.flow_control_rate = 3  # Will be loaded from config if available
        self.bw_packet_length = 900  # bytes (will be loaded from config if available)
        self.bw_test_start_time = None  # Timestamp when bandwidth test started
        self.bw_test_duration = 30.0  # seconds
        self.test_result_received = None  # Timestamp when TEST_RESULT was first received
        self.test_result_data = None  # Store TEST_RESULT statistics
        self.test_result_guid = None  # GUID from TEST_RESULT for acking
        # Circular buffer for FLOW_CONTROL SequenceSpans
        from collections import deque
        self.flow_control_buffer = deque(maxlen=self.flow_control_rate)
        self.working_sequence_span = None  # Current working SequenceSpan
        # Generate dummy data for bandwidth test packets
        alphabet_nums_symbols = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?/~`'
        self.dummy_data_base = alphabet_nums_symbols
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
    
    def should_drop_packet(self) -> bool:
        """Check if packet should be dropped based on test_drop_rate"""
        if self.test_drop_rate > 0:
            return random.random() < self.test_drop_rate
        return False
    
    def start(self):
        """Start the client and connect to server"""
        self.running = True
        
        # Create main socket
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        print(f"Connecting to server {self.server_addr}:{self.server_port}")
        sys.stdout.flush()
        
        # Wait for port assignment with retry loop
        self.main_socket.settimeout(1.0)
        connected = False
        for attempt in range(5):
            # Send connection request
            if not self.should_drop_packet():
                self.main_socket.sendto(b"CONNECT", (self.server_addr, self.server_port))
            
            try:
                # Parse response: "port1,port2,port3,heartbeat_key"
                data, _ = self.main_socket.recvfrom(4096)
                ports_str = data.decode()
                self.control_port, self.upload_port, self.download_port, self.heartbeat_key = map(int, ports_str.split(','))
                connected = True
                break
            except socket.timeout:
                continue
        
        if not connected:
            print("Timeout waiting for server response", file=sys.stderr)
            sys.stderr.flush()
            self.running = False
            return
        
        try:
            
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

            if not self.should_drop_packet():
                self.control_socket.sendto(msg_ctrl, (self.server_addr, self.control_port))
            if not self.should_drop_packet():
                self.upload_socket.sendto(msg_up, (self.server_addr, self.upload_port))
            if not self.should_drop_packet():
                self.download_socket.sendto(msg_down, (self.server_addr, self.download_port))
            
            print("Client connected successfully")
            sys.stdout.flush()
            
            # Initialize heartbeat timing
            self.last_heartbeat = time.time()
            
            # If --bwup flag is set, send bandwidth upload test command
            if self.bwup:
                self.send_bwup_test()
            
            # Run main client communication loop
            self.client_comm_loop()
            
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
            
            # Check if BWUP needs resending
            if self.bwup and not self.bwup_acked and self.bwup_last_sent > 0:
                time_since_last_send = (current_time - self.bwup_last_sent) * 1000  # Convert to milliseconds
                if time_since_last_send > self.ucm_delay:
                    self.send_bwup_test()
            
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
                    # Not a heartbeat - check for CONTROL, FLOW_CONTROL, and TEST_RESULT messages
                    if mt == MessageType.TEST_RESULT and label == 'CONTROL' and isinstance(json_obj, dict):
                        # Received TEST_RESULT from server with statistics
                        guid = json_obj.get('guid')
                        if guid:
                            if self.test_result_received is None:
                                # First time receiving TEST_RESULT
                                self.test_result_received = time.time()
                                self.test_result_data = json_obj
                                self.test_result_guid = guid
                                
                                if self.test_verbose:
                                    print(f"Client received TEST_RESULT: bandwidth={json_obj.get('bandwidth_bps', 0):.2f} bps, bytes={json_obj.get('bytes_received', 0)}, retransmits={json_obj.get('retransmit_count', 0)}", file=sys.stderr)
                                    sys.stderr.flush()
                            
                            # Send ACK back to server
                            ack_params = {'cmd': 'TEST_RESULT', 'ack': 0, 'guid': guid}
                            seq = self.get_and_increment_sequence(self.control_port, data_channel)
                            ack_msg = MessagePacket.format_packet(MessageType.TEST_RESULT, data_channel, seq, 0, ack_params)
                            if not self.should_drop_packet():
                                self.control_socket.sendto(ack_msg, (self.server_addr, self.control_port))
                            
                            if self.test_verbose:
                                print(f"Client sent TEST_RESULT ack for guid {guid}", file=sys.stderr)
                                sys.stderr.flush()
                    elif mt == MessageType.CONTROL and label == 'CONTROL' and isinstance(json_obj, dict):
                        cmd = json_obj.get('cmd')
                        if cmd == 'BWUP' and json_obj.get('ack') == 0:
                            # Received CONTROL ack for BWUP
                            self.bwup_acked = True
                            self.bw_test_start_time = time.time()  # Start the bandwidth test timer
                            if self.test_verbose:
                                print(f"Client received BWUP ack from server, starting bandwidth test", file=sys.stderr)
                                sys.stderr.flush()
                    elif mt == MessageType.FLOW_CONTROL and label == 'UPLOAD':
                        # Received FLOW_CONTROL message - decode binary data
                        
                        # Parse binary payload to create SequenceSpan
                        try:
                            # Get binary data from packet (everything after 20-byte header)
                            binary_data = data[MessagePacket.HEADER_LEN:]
                            if binary_data:
                                # Create SequenceSpan from binary data
                                sequence_span = SequenceSpan.from_binary(binary_data)
                                
                                if self.test_verbose:
                                    print(f"Client received FLOW_CONTROL on channel {data_channel}, spans: {sequence_span.spans}", file=sys.stderr)
                                    sys.stderr.flush()
                                
                                # Check if buffer is full - if so, compare oldest with new to find dropped packets
                                if len(self.flow_control_buffer) == self.flow_control_buffer.maxlen:
                                    # Get the oldest span (will be evicted when we append)
                                    oldest_span = self.flow_control_buffer[0]
                                    
                                    # Find sequence spans that exist in both old and new spans (dropped packets)
                                    # These are sequences the server still expects but we haven't sent
                                    dropped_span_ranges = []
                                    for old_begin, old_end in oldest_span.spans:
                                        for new_begin, new_end in sequence_span.spans:
                                            # Find overlap between spans
                                            overlap_begin = max(old_begin, new_begin)
                                            overlap_end = min(old_end, new_end)
                                            if overlap_begin <= overlap_end:
                                                # Add the overlap as a span range (don't iterate!)
                                                dropped_span_ranges.append((overlap_begin, overlap_end))
                                    
                                    # Add dropped span ranges to working_sequence_span for retransmission
                                    if dropped_span_ranges and self.working_sequence_span:
                                        # Add spans directly to working sequence span
                                        self.working_sequence_span.spans.extend(dropped_span_ranges)
                                        # Re-sort spans to maintain order
                                        self.working_sequence_span.spans.sort(key=lambda x: x[0])
                                        
                                        # Merge overlapping and adjacent spans
                                        merged_spans = []
                                        for begin, end in self.working_sequence_span.spans:
                                            if merged_spans and begin <= merged_spans[-1][1] + 1:
                                                # Overlapping or adjacent - merge with previous span
                                                merged_spans[-1] = (merged_spans[-1][0], max(merged_spans[-1][1], end))
                                            else:
                                                # Non-overlapping - add as new span
                                                merged_spans.append((begin, end))
                                        self.working_sequence_span.spans = merged_spans
                                        
                                        if self.test_verbose:
                                            print(f"Client detected {len(dropped_span_ranges)} dropped span ranges, added to working span", file=sys.stderr)
                                            sys.stderr.flush()
                                
                                # Add to circular buffer
                                self.flow_control_buffer.append(sequence_span)
                                
                                # Set as working_sequence_span if None
                                if self.working_sequence_span is None:
                                    self.working_sequence_span = sequence_span
                                    if self.test_verbose:
                                        print(f"Client set working_sequence_span from FLOW_CONTROL", file=sys.stderr)
                                        sys.stderr.flush()
                        except Exception as e:
                            if self.test_verbose:
                                print(f"Error decoding FLOW_CONTROL binary data: {e}", file=sys.stderr)
                                sys.stderr.flush()
                    # Continue to next packet after handling CONTROL/FLOW_CONTROL
                    continue

                # Handle heartbeat messages
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
                    if not self.should_drop_packet():
                        sock.sendto(resp, (self.server_addr, port))
            
            # Send bandwidth test packets if in test mode
            self.send_bandwidth_test_packets()
            
            # Check if we should shutdown after receiving TEST_RESULT
            if self.test_result_received is not None:
                elapsed = current_time - self.test_result_received
                if elapsed >= 5.0:  # 5 seconds of acking
                    # Print statistics and shutdown
                    if self.test_result_data:
                        bandwidth_bps = self.test_result_data.get('bandwidth_bps', 0)
                        bandwidth_mbps = bandwidth_bps / (1024 * 1024)
                        bytes_received = self.test_result_data.get('bytes_received', 0)
                        retransmit_count = self.test_result_data.get('retransmit_count', 0)
                        duration = self.test_result_data.get('duration', 0)
                        
                        print(f"\n=== Upload Bandwidth Test Results ===")
                        print(f"Duration: {duration:.2f} seconds")
                        print(f"Bytes Received: {bytes_received}")
                        print(f"Bandwidth: {bandwidth_bps:.2f} bps ({bandwidth_mbps:.2f} Mbps)")
                        print(f"Retransmitted Packets: {retransmit_count}")
                        sys.stdout.flush()
                    
                    # Stop the client
                    self.running = False
                    return
            
            # Test delay if configured
            if self.test_delay > 0:
                time.sleep(self.test_delay / 1000.0)
    
    def send_bandwidth_test_packets(self):
        """Send bandwidth test packets if in test mode and have working_sequence_span"""
        # Check if we're in bandwidth test mode
        if not self.bw_test_start_time:
            return
        
        # Check if test has expired (30 seconds)
        current_time = time.time()
        elapsed = current_time - self.bw_test_start_time
        if elapsed >= self.bw_test_duration:
            self.bw_test_start_time = None  # End the test
            if self.test_verbose:
                print(f"Client bandwidth test completed (30 seconds)", file=sys.stderr)
                sys.stderr.flush()
            return
        
        # Check if we have a working sequence span and the channel
        if not self.working_sequence_span or not self.bwup_channel:
            return
        
        # Send packets without blocking - send as many as we can in this iteration
        # Typically send a few packets per iteration to maintain throughput
        packets_per_iteration = 1

        # Generate dummy data to target length
        repeats_needed = (self.bw_packet_length + len(self.dummy_data_base) - 1) // len(self.dummy_data_base)
        dummy_data = (self.dummy_data_base * repeats_needed)[:self.bw_packet_length]
        
        # Create JSON payload
        json_payload = {'dummy_data': dummy_data}

        for _ in range(packets_per_iteration):
            # Get the actual channel sequence number (incrementing counter)
            channel_seq_num = self.get_and_increment_sequence(self.upload_port, self.bwup_channel)
            
            # Get expected sequence number from working span
            expected_seq_num = self.working_sequence_span.get_lowest()
            if expected_seq_num is None:
                # No more sequence numbers available
                break
            
            # Calculate sequence_offset if we're retransmitting
            if channel_seq_num != expected_seq_num:
                seq_offset = channel_seq_num - expected_seq_num
            else:
                seq_offset = 0
            
            try:
                
                # Create BANDWIDTH_TEST packet with sequence_offset
                message = MessagePacket.format_packet(
                    MessageType.BANDWIDTH_TEST,
                    self.bwup_channel,
                    channel_seq_num,
                    seq_offset,
                    json_payload
                )
                
                # Send on upload port
                if not self.should_drop_packet():
                    self.upload_socket.sendto(message, (self.server_addr, self.upload_port))
                
                # Verbose logging
                if self.test_verbose:
                    if seq_offset != 0:
                        print(f"Client sent BANDWIDTH_TEST packet channel_seq={channel_seq_num}, expected_seq={expected_seq_num}, offset={seq_offset} on channel {self.bwup_channel}", file=sys.stderr)
                    else:
                        print(f"Client sent BANDWIDTH_TEST packet seq={channel_seq_num} on channel {self.bwup_channel}", file=sys.stderr)
                    sys.stderr.flush()
                
            except Exception as e:
                if self.test_verbose:
                    print(f"Error sending bandwidth test packet: {e}", file=sys.stderr)
                    sys.stderr.flush()
                break
    
    def send_heartbeat(self):
        """Send heartbeat with timestamp to server"""
        timestamp = time.time()
        json_obj = {'timestamp': timestamp}
        # Send heartbeats on per-port sockets using heartbeat_key in data_channel
        try:
            if self.control_socket and self.control_port:
                seq_ctrl = self.get_and_increment_sequence(self.control_port, self.heartbeat_key)
                message_ctrl = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_ctrl, 0, json_obj)
                if not self.should_drop_packet():
                    self.control_socket.sendto(message_ctrl, (self.server_addr, self.control_port))
        except Exception:
            pass
        try:
            if self.upload_socket and self.upload_port:
                seq_up = self.get_and_increment_sequence(self.upload_port, self.heartbeat_key)
                message_up = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_up, 0, json_obj)
                if not self.should_drop_packet():
                    self.upload_socket.sendto(message_up, (self.server_addr, self.upload_port))
        except Exception:
            pass
        try:
            if self.download_socket and self.download_port:
                seq_down = self.get_and_increment_sequence(self.download_port, self.heartbeat_key)
                message_down = MessagePacket.format_packet(MessageType.HEARTBEAT_0, self.heartbeat_key, seq_down, 0, json_obj)
                if not self.should_drop_packet():
                    self.download_socket.sendto(message_down, (self.server_addr, self.download_port))
        except Exception:
            pass
    
    def send_bwup_test(self):
        """Send BWUP control message to initiate 30-second upload bandwidth test"""
        # Generate random channel number (1 to max 3-byte positive int, but not heartbeat_key)
        max_3byte = (2 ** 24) - 1  # 16777215
        
        # Only generate new channel if we don't have one yet
        if self.bwup_channel is None:
            while True:
                channel = random.randint(1, max_3byte)
                if channel != self.heartbeat_key:
                    break
            self.bwup_channel = channel
        else:
            channel = self.bwup_channel
        
        # Create CONTROL message with BWUP command
        json_payload = {
            'cmd': 'BWUP',
            'channel': channel
        }
        
        # Send CONTROL message on control port
        try:
            seq = self.get_and_increment_sequence(self.control_port, channel)
            message = MessagePacket.format_packet(MessageType.CONTROL, channel, seq, 0, json_payload)
            if not self.should_drop_packet():
                self.control_socket.sendto(message, (self.server_addr, self.control_port))
            self.bwup_last_sent = time.time()
            if self.test_verbose:
                print(f"Client sent BWUP packet on channel {channel}", file=sys.stderr)
                sys.stderr.flush()
        except Exception as e:
            print(f"Error sending BWUP test command: {e}", file=sys.stderr)
            sys.stderr.flush()
    
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
        '--bwup',
        action='store_true',
        help='Start a 30-second upload bandwidth test when connecting in client mode'
    )
    parser.add_argument(
        '--test-verbose',
        action='store_true',
        help='Print verbose test/debug messages for control packets (default: False)'
    )
    parser.add_argument(
        '--test-delay',
        type=int,
        nargs='?',
        const=100,
        metavar='milliseconds',
        help='Add delay in communication loops for testing (default: 100ms if flag used, 0 if not)'
    )
    parser.add_argument(
        '--test-drop-rate',
        type=float,
        metavar='probability',
        help='Probability (0.0-1.0) of dropping packets for testing (default: 0.0)'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'wyndrvr {__version__}'
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
        
        # Set test_verbose flag
        if args.test_verbose:
            config.test_verbose = True
        
        # Set test_delay if provided
        if args.test_delay is not None:
            config.test_delay = args.test_delay
        
        # Set test_drop_rate if provided
        if args.test_drop_rate is not None:
            config.test_drop_rate = args.test_drop_rate
        
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
        
        # Load config to get client_block_time and test_delay if available
        block_time = 100  # default
        test_delay = 0 if args.test_delay is None else args.test_delay  # default 0, or value from args
        test_drop_rate = 0.0 if args.test_drop_rate is None else args.test_drop_rate  # default 0.0, or value from args
        config = None
        if config_path.exists():
            server = WyndServer(ServerConfig())
            config = server.load_config(config_path)
            block_time = config.client_block_time
            # Only override test_delay from config if not specified on command line
            if args.test_delay is None:
                test_delay = config.test_delay
            # Only override test_drop_rate from config if not specified on command line
            if args.test_drop_rate is None:
                test_drop_rate = config.test_drop_rate
        
        client = WyndClient(addr, port, block_time, bwup=args.bwup, test_verbose=args.test_verbose, test_delay=test_delay, test_drop_rate=test_drop_rate)
        # Set heartbeat interval from config if present (milliseconds -> seconds)
        try:
            if config:
                client.heartbeat_interval = config.heartbeat_rate / 1000.0
                client.ucm_delay = config.ucm_delay
                client.flow_control_rate = config.flow_control_rate
                client.bw_packet_length = config.bw_packet_length
                # Update circular buffer maxlen if flow_control_rate changed
                from collections import deque
                client.flow_control_buffer = deque(client.flow_control_buffer, maxlen=client.flow_control_rate)
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
