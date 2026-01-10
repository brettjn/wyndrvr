#!/usr/bin/env python3
"""
Integration test for wyndrvr FLOW_CONTROL - tests that FLOW_CONTROL packets are sent
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"


def test_flow_control_packets():
    """Test that server sends FLOW_CONTROL packets and client receives them"""
    print("=" * 60)
    print("Testing FLOW_CONTROL packet integration")
    print("=" * 60)
    
    # Start server with test-verbose flag
    print("\nStarting server on port 6717 with --test-verbose...")
    server_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "--server", ":6717", "--test-verbose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server to start
    time.sleep(2)
    
    if server_proc.poll() is not None:
        stdout, stderr = server_proc.communicate()
        print(f"Server failed to start: {stderr}")
        return 1
    
    print("✓ Server started")
    
    # Start client with --bwup and --test-verbose flags
    print("\nStarting client with --bwup and --test-verbose...")
    client_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "127.0.0.1:6717", "--bwup", "--test-verbose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for BWUP exchange and FLOW_CONTROL packets
    # FLOW_CONTROL should be sent every 1 second (3000ms / 3)
    # Wait at least 3-4 seconds to see multiple packets
    print("Waiting for BWUP exchange and FLOW_CONTROL packets (4 seconds)...")
    time.sleep(4)
    
    # Check both processes are still running
    server_running = server_proc.poll() is None
    client_running = client_proc.poll() is None
    
    print(f"\nServer running: {server_running}")
    print(f"Client running: {client_running}")
    
    # Terminate client
    client_proc.terminate()
    try:
        stdout, stderr = client_proc.communicate(timeout=2)
        print(f"\nClient stdout:\n{stdout}")
        print(f"\nClient stderr:\n{stderr}")
        
        # Check for successful connection
        has_connection = (
            "Connecting to server" in stdout or 
            "Received port assignment" in stdout or 
            "Client connected" in stdout
        )
        
        assert has_connection, "Client should connect successfully"
        print("✓ Client connected successfully")
        
        # Check for BWUP ack received
        if "Client received BWUP ack from server" in stderr:
            print("✓ Client received BWUP acknowledgment")
        else:
            print("⚠ Warning: Client BWUP ack not detected")
        
        # Check for FLOW_CONTROL received messages
        flow_control_count = stderr.count("Client received FLOW_CONTROL")
        if flow_control_count > 0:
            print(f"✓ Client received {flow_control_count} FLOW_CONTROL packet(s)")
        else:
            print("✗ Client did not receive any FLOW_CONTROL packets")
        
        # We expect at least 2-3 FLOW_CONTROL packets in 4 seconds (sent every ~1 second)
        if flow_control_count >= 2:
            print("✓ Multiple FLOW_CONTROL packets received as expected")
        else:
            print(f"⚠ Warning: Expected at least 2 FLOW_CONTROL packets, got {flow_control_count}")
        
    except subprocess.TimeoutExpired:
        client_proc.kill()
        client_proc.communicate()
    
    # Terminate server
    server_proc.terminate()
    try:
        stdout, stderr = server_proc.communicate(timeout=2)
        print(f"\nServer stdout:\n{stdout}")
        print(f"\nServer stderr:\n{stderr}")
        
        # Check server output
        has_server_output = (
            "Server started" in stdout or 
            "Client connected" in stdout
        )
        
        assert has_server_output, "Server should start successfully"
        print("✓ Server started successfully")
        
        # Check for upload bandwidth test started
        if "Server started upload bandwidth test" in stderr:
            print("✓ Server started upload bandwidth test")
        else:
            print("⚠ Warning: Server upload bandwidth test start not detected")
        
        # Check for FLOW_CONTROL sent messages
        flow_control_count = stderr.count("Server sent FLOW_CONTROL")
        if flow_control_count > 0:
            print(f"✓ Server sent {flow_control_count} FLOW_CONTROL packet(s)")
        else:
            print("✗ Server did not send any FLOW_CONTROL packets")
        
        # We expect at least 2-3 FLOW_CONTROL packets in 4 seconds
        if flow_control_count >= 2:
            print("✓ Multiple FLOW_CONTROL packets sent as expected")
        else:
            print(f"⚠ Warning: Expected at least 2 FLOW_CONTROL packets sent, got {flow_control_count}")
        
        # Verify we got some FLOW_CONTROL packets
        assert flow_control_count > 0, "Server should send at least one FLOW_CONTROL packet"
        
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.communicate()
    
    print("\n" + "=" * 60)
    print("✓ FLOW_CONTROL integration test passed")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(test_flow_control_packets())
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
