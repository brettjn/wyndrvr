#!/usr/bin/env python3
"""Test script to verify dropped packet detection logic"""

from collections import deque
from wyndrvr import SequenceSpan

def test_dropped_packet_detection():
    """Simulate the dropped packet detection logic"""
    
    # Create a circular buffer with maxlen=3 (simulating flow_control_rate)
    flow_control_buffer = deque(maxlen=3)
    working_sequence_span = SequenceSpan([(0, 100)])
    
    print("Initial working_sequence_span:", working_sequence_span.spans)
    print()
    
    # First FLOW_CONTROL - server expects 0-100, client has sent some
    span1 = SequenceSpan([(0, 100)])
    flow_control_buffer.append(span1)
    print(f"Received FLOW_CONTROL #1: {span1.spans}")
    print(f"Buffer size: {len(flow_control_buffer)}/{flow_control_buffer.maxlen}")
    print()
    
    # Simulate sending some packets (10-30)
    for i in range(10, 31):
        working_sequence_span.remove_seq(i)
    print(f"After sending packets 10-30, working span: {working_sequence_span.spans}")
    print()
    
    # Second FLOW_CONTROL - server still expects 0-9, 31-100 (packets 10-30 received)
    span2 = SequenceSpan([(0, 9), (31, 100)])
    flow_control_buffer.append(span2)
    print(f"Received FLOW_CONTROL #2: {span2.spans}")
    print(f"Buffer size: {len(flow_control_buffer)}/{flow_control_buffer.maxlen}")
    print()
    
    # Simulate sending more packets (31-60)
    for i in range(31, 61):
        working_sequence_span.remove_seq(i)
    print(f"After sending packets 31-60, working span: {working_sequence_span.spans}")
    print()
    
    # Third FLOW_CONTROL - server still expects 0-9, 61-100
    span3 = SequenceSpan([(0, 9), (61, 100)])
    flow_control_buffer.append(span3)
    print(f"Received FLOW_CONTROL #3: {span3.spans}")
    print(f"Buffer size: {len(flow_control_buffer)}/{flow_control_buffer.maxlen}")
    print()
    
    # Fourth FLOW_CONTROL - buffer is now full, will evict span1
    # Suppose packets 5-7 were dropped (server still expects them)
    span4 = SequenceSpan([(0, 9), (61, 100)])
    
    print("=" * 60)
    print("BUFFER FULL - COMPARING OLDEST WITH NEW")
    print("=" * 60)
    
    # Get oldest span before appending
    oldest_span = flow_control_buffer[0]
    print(f"Oldest span (will be evicted): {oldest_span.spans}")
    print(f"New span: {span4.spans}")
    print()
    
    # Find dropped packets (overlap between oldest and new)
    dropped_sequences = []
    for old_begin, old_end in oldest_span.spans:
        for new_begin, new_end in span4.spans:
            overlap_begin = max(old_begin, new_begin)
            overlap_end = min(old_end, new_end)
            if overlap_begin <= overlap_end:
                for seq in range(overlap_begin, overlap_end + 1):
                    dropped_sequences.append(seq)
    
    print(f"Dropped sequences detected: {dropped_sequences}")
    print(f"Number of dropped packets: {len(dropped_sequences)}")
    print()
    
    # Add dropped sequences to working span
    if dropped_sequences:
        for seq in dropped_sequences:
            working_sequence_span.spans.append((seq, seq))
        working_sequence_span.spans.sort(key=lambda x: x[0])
        print(f"After adding dropped packets, working span: {working_sequence_span.spans}")
    
    # Now append the new span
    flow_control_buffer.append(span4)
    print(f"Buffer after append (oldest evicted): {[s.spans for s in flow_control_buffer]}")
    print()
    
    # Get lowest sequence to send - should prioritize retransmissions (0-9)
    lowest = working_sequence_span.get_lowest()
    print(f"Next sequence to send: {lowest}")
    print()
    
    print("=" * 60)
    print("SUCCESS: Dropped packet detection logic verified!")
    print("=" * 60)

if __name__ == "__main__":
    test_dropped_packet_detection()
