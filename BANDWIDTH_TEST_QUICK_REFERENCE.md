# BANDWIDTH_TEST Quick Reference

## Implementation Complete ✓

### Key Features
1. **SequenceSpan.get_lowest()** - Returns and removes lowest sequence number from spans
2. **bw_packet_length** - Config parameter (default 900 bytes) for packet payload size
3. **Dummy data** - Alphabet, numbers, and ASCII symbols repeated to fill packet
4. **BANDWIDTH_TEST packets** - Sent continuously for 30 seconds without blocking
5. **Non-blocking design** - Doesn't interfere with heartbeats or control messages

### Configuration
```ini
# In config file:
bw_packet_length=900        # Packet payload size in bytes
ucm_delay=100              # Control message retransmission delay (ms)
adjustment_delay=3000       # Flow control interval (ms)
flow_control_rate=3        # Flow control packets per interval
```

### Usage
```bash
# Start bandwidth test
./wyndrvr.py --bwup 127.0.0.1:6711

# With verbose output
./wyndrvr.py --bwup --test-verbose 127.0.0.1:6711

# With custom config
./wyndrvr.py --bwup --config myconfig.conf 127.0.0.1:6711
```

### Test Execution Flow
1. Client connects and requests port assignment
2. Client sends BWUP command on control port
3. Server acknowledges and starts 30-second bandwidth test mode
4. Server sends FLOW_CONTROL packets with sequence spans (every 1-3 seconds)
5. Client receives FLOW_CONTROL and populates working_sequence_span
6. Client continuously sends BANDWIDTH_TEST packets:
   - Gets sequence from working_sequence_span.get_lowest()
   - Generates 900 bytes of dummy data
   - Sends packet on upload port
   - Repeats until 30 seconds elapsed or sequences exhausted

### Packet Structure
```
BANDWIDTH_TEST Packet:
├── Header (20 bytes)
│   ├── Type: 4 (BANDWIDTH_TEST)
│   ├── Channel: <from FLOW_CONTROL>
│   ├── Sequence: <from get_lowest()>
│   └── Offset: 0
└── Payload (JSON)
    └── {"dummy_data": "ABC...xyz123..."}  # 900 bytes
```

### Code Locations
- SequenceSpan.get_lowest(): [wyndrvr.py#L260](wyndrvr.py#L260-L286)
- send_bandwidth_test_packets(): [wyndrvr.py#L1420](wyndrvr.py#L1420-L1476)
- bw_packet_length config: [wyndrvr.py#L309](wyndrvr.py#L309)
- Dummy data generation: [wyndrvr.py#L1195](wyndrvr.py#L1195-L1197)
- Packet sending in loop: [wyndrvr.py#L1418](wyndrvr.py#L1418)

### Tests
```bash
# Run bandwidth test-related tests
python3 -m pytest tests/test_bandwidth_test_packets.py -v
python3 -m pytest tests/test_bwup_integration.py -v
python3 -m pytest tests/test_flow_control_integration.py -v

# All tests
python3 -m pytest tests/ -v
```

### Performance
- **Packet Rate**: ~10 packets per client loop iteration
- **Loop Frequency**: ~100Hz (10ms non-blocking)
- **Theoretical Max**: ~1000 packets/second
- **Packet Size**: ~920+ bytes (20 header + 900 data + JSON overhead)
- **Bandwidth**: ~7.4 Mbps theoretical maximum

### Key Implementation Details
1. **Non-blocking**: Uses existing client_comm_loop, no sleeps or waits
2. **Sequence Management**: get_lowest() efficiently removes used sequences
3. **Timeout**: Automatically stops after 30 seconds
4. **Flow Control**: Server provides sequence spans via FLOW_CONTROL packets
5. **Circular Buffer**: Client maintains buffer of SequenceSpans (size = flow_control_rate)
6. **Working Span**: Client uses working_sequence_span for current batch of sequences

### Version
- **Version**: 0.7
- **Status**: Complete and tested
- **Date**: 2024

### Notes
- Server doesn't need to respond to BANDWIDTH_TEST packets
- Packets are just received and can be counted for bandwidth calculation
- Test runs for exactly 30 seconds from first BWUP acknowledgment
- Client handles sequence exhaustion gracefully (waits for more FLOW_CONTROL)
- All existing tests continue to pass
