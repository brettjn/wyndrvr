# Bandwidth Test Implementation Summary

## Overview
This document summarizes the implementation of BANDWIDTH_TEST packet generation and sending functionality in wyndrvr version 0.7.

## Components Implemented

### 1. SequenceSpan.get_lowest() Method
**Location**: [wyndrvr.py](wyndrvr.py#L260-L286)

**Functionality**:
- Returns the lowest sequence number from the spans list
- Removes that sequence number from the span
- If a span is `(0, 1000)`, calling `get_lowest()` returns `0` and changes the span to `(1, 1000)`
- If a span contains only one value `(1000, 1000)`, it returns `1000` and removes the span entirely
- Returns `None` when no sequences are available
- Handles multiple non-contiguous spans by finding the span with the lowest begin value

**Example**:
```python
span = SequenceSpan(spans=[(100, 105), (200, 202), (50, 52)])
span.get_lowest()  # Returns 50
span.get_lowest()  # Returns 51
span.get_lowest()  # Returns 52
span.get_lowest()  # Returns 100 (moves to next span)
```

### 2. bw_packet_length Configuration Parameter
**Location**: [wyndrvr.py](wyndrvr.py#L309)

**Default Value**: 900 bytes

**Configuration**:
- Added to `ServerConfig` dataclass with default of 900
- Added to config file template at [wyndrvr.py](wyndrvr.py#L863-L864)
- Added to config file parsing at [wyndrvr.py](wyndrvr.py#L821)
- Loaded into client from config at [wyndrvr.py](wyndrvr.py#L1642)

**Purpose**: Controls the size of the dummy_data payload in BANDWIDTH_TEST packets

### 3. Dummy Data Generation
**Location**: [wyndrvr.py](wyndrvr.py#L1195-L1197)

**Implementation**:
- Base string contains alphabet (upper/lower), digits, and ASCII symbols
- String: `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?/~``
- Repeated to reach `bw_packet_length` bytes
- Generated once during WyndClient initialization and stored in `self.dummy_data_base`

### 4. Bandwidth Test State Tracking
**Location**: [wyndrvr.py](wyndrvr.py#L1191-L1193)

**New Fields**:
- `bw_test_start_time`: Timestamp when bandwidth test started (set when BWUP ack received)
- `bw_test_duration`: Duration of test in seconds (default 30.0)
- `bw_packet_length`: Packet payload size in bytes (default 900)

**Test Start**: Set when client receives BWUP acknowledgment at [wyndrvr.py](wyndrvr.py#L1361-L1365)

### 5. send_bandwidth_test_packets() Method
**Location**: [wyndrvr.py](wyndrvr.py#L1420-L1476)

**Functionality**:
1. Checks if bandwidth test is active (`bw_test_start_time` is set)
2. Verifies test hasn't expired (30 seconds)
3. Checks for available sequence span and channel
4. Sends up to 10 packets per iteration (configurable via `packets_per_iteration`)
5. For each packet:
   - Gets sequence number via `working_sequence_span.get_lowest()`
   - Generates dummy_data of `bw_packet_length` bytes
   - Creates JSON payload: `{'dummy_data': dummy_data}`
   - Creates BANDWIDTH_TEST packet with proper headers
   - Sends on upload socket to server's upload port

**Non-blocking Design**:
- Called from main client_comm_loop at [wyndrvr.py](wyndrvr.py#L1418)
- Doesn't use any blocking operations
- Sends multiple packets per iteration for throughput
- Returns immediately if no sequences available
- Doesn't interfere with heartbeats, CONTROL, or FLOW_CONTROL messages

### 6. Packet Format
**Type**: MessageType.BANDWIDTH_TEST (value 4)

**Structure**:
- 20-byte header (message type, channel, sequence, offset)
- JSON payload: `{"dummy_data": "<repeated alphabet/numbers/symbols>"}`
- Total size: ~920+ bytes (20 byte header + 900 byte payload + JSON overhead)

**Example**:
```
Header:
  Type: 4 (BANDWIDTH_TEST)
  Channel: <bwup_channel from FLOW_CONTROL>
  Sequence: <from working_sequence_span.get_lowest()>
  Offset: 0

Payload:
  {"dummy_data": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz..."}
```

## Testing

### Unit Tests
**File**: [tests/test_bandwidth_test_packets.py](tests/test_bandwidth_test_packets.py)

**Tests**:
1. `test_sequence_span_get_lowest()`: Verifies get_lowest() method behavior
   - Single span exhaustion
   - Multiple span handling
   - Empty span returns None
   
2. `test_bandwidth_packet_format()`: Verifies packet structure
   - Correct dummy_data length
   - Proper JSON encoding
   - Valid MessagePacket format

### Integration Tests
**Existing Tests**: All passing
- `test_bwup_integration.py`: BWUP command/acknowledgment
- `test_flow_control_integration.py`: FLOW_CONTROL packet handling
- Tests verify end-to-end functionality

## Configuration Example

```ini
# wyndrvr configuration file

# Bandwidth test packet length (bytes)
bw_packet_length=900

# Upload control message delay (milliseconds)
ucm_delay=100

# Flow control ms
adjustment_delay=3000
flow_control_rate=3
```

## Usage

### Client Mode with Bandwidth Test
```bash
# Start bandwidth test
./wyndrvr.py --bwup --test-verbose 127.0.0.1:6711

# With custom config
./wyndrvr.py --bwup --config myconfig.conf 127.0.0.1:6711
```

### Expected Behavior
1. Client sends PORT_ASSIGNMENT request
2. Server assigns ports and responds
3. Client sends BWUP command on control port
4. Server acknowledges and starts bandwidth test mode
5. Server sends FLOW_CONTROL packets every second with sequence spans
6. Client receives FLOW_CONTROL and populates working_sequence_span
7. Client continuously sends BANDWIDTH_TEST packets for 30 seconds
8. Test completes after 30 seconds

## Performance Characteristics

- **Packet Rate**: 10 packets per client loop iteration
- **Loop Speed**: Non-blocking, ~100Hz (10ms block_time)
- **Theoretical Max**: ~1000 packets/second
- **Packet Size**: ~920+ bytes per packet
- **Bandwidth**: ~7.4 Mbps theoretical max (at 1000 pkt/s)

## Future Enhancements

Potential improvements:
1. Server-side bandwidth calculation from received packets
2. Adjustable packets_per_iteration based on available sequences
3. TCP window-like flow control for better throughput
4. Bandwidth result reporting at test completion
5. Variable packet size testing
6. Bi-directional bandwidth testing (upload + download)

## Version
**Version**: 0.7
**Date**: 2024
**Status**: Complete and tested
