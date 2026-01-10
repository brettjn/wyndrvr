#!/usr/bin/env python3
"""
Integration test for bandwidth test packet sending
"""

import sys
import os
import time
import socket
import json
import struct

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wyndrvr import SequenceSpan, MessageType, MessagePacket


def test_sequence_span_get_lowest():
    """Test SequenceSpan.get_lowest() method"""
    
    # Create sequence span with single range
    span = SequenceSpan(spans=[(0, 10)])
    
    # Get lowest should return 0 and adjust span to (1, 10)
    assert span.get_lowest() == 0
    assert span.spans == [(1, 10)]
    
    # Get more values
    assert span.get_lowest() == 1
    assert span.get_lowest() == 2
    assert span.spans == [(3, 10)]
    
    # Get until span has one value
    for i in range(3, 10):
        assert span.get_lowest() == i
    
    # Last value
    assert span.get_lowest() == 10
    assert span.spans == []
    
    # No more values
    assert span.get_lowest() is None
    
    # Multiple spans
    span2 = SequenceSpan(spans=[(100, 105), (200, 202), (50, 52)])
    
    # Should get from lowest span (50-52) first
    assert span2.get_lowest() == 50
    assert span2.get_lowest() == 51
    assert span2.get_lowest() == 52
    
    # Now from 100-105
    assert span2.get_lowest() == 100
    
    print("SequenceSpan.get_lowest() tests passed!")
    return 0


def test_bandwidth_packet_format():
    """Test BANDWIDTH_TEST packet format"""
    
    # Generate dummy data
    alphabet_nums_symbols = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|;:,.<>?/~`'
    bw_packet_length = 500
    
    # Repeat to target length
    repeats_needed = (bw_packet_length + len(alphabet_nums_symbols) - 1) // len(alphabet_nums_symbols)
    dummy_data = (alphabet_nums_symbols * repeats_needed)[:bw_packet_length]
    
    # Verify length
    assert len(dummy_data) == bw_packet_length
    
    # Create packet
    json_payload = {'dummy_data': dummy_data}
    message = MessagePacket.format_packet(
        MessageType.BANDWIDTH_TEST,
        12345,  # channel
        42,     # sequence
        0,      # offset
        json_payload
    )
    
    # Verify packet structure
    assert len(message) > 20  # Header + payload
    
    # Parse header
    msg_type_val = message[0]
    channel = struct.unpack('>I', b'\x00' + message[1:4])[0]
    sequence = struct.unpack('>Q', message[4:12])[0]
    offset = struct.unpack('>Q', message[12:20])[0]
    
    assert msg_type_val == MessageType.BANDWIDTH_TEST.value
    assert channel == 12345
    assert sequence == 42
    assert offset == 0
    
    # Parse payload
    payload = message[20:].decode('utf-8')
    json_obj = json.loads(payload)
    
    assert 'dummy_data' in json_obj
    assert len(json_obj['dummy_data']) == bw_packet_length
    
    print("BANDWIDTH_TEST packet format tests passed!")
    return 0


if __name__ == '__main__':
    result1 = test_sequence_span_get_lowest()
    result2 = test_bandwidth_packet_format()
    
    if result1 == 0 and result2 == 0:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
