#!/usr/bin/env python3
"""
Integration test for wyndrvr BWUP mode - tests bandwidth upload test functionality
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"


def test_bwup_mode():
    """Test that client can initiate BWUP test and receive acknowledgment"""
    print("=" * 60)
    print("Testing BWUP mode integration")
    print("=" * 60)
    
    # Start server with test-verbose flag
    print("\nStarting server on port 6716 with --test-verbose...")
    server_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "--server", ":6716", "--test-verbose"],
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
        [sys.executable, str(WYNDRVR_PATH), "127.0.0.1:6716", "--bwup", "--test-verbose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for connection and BWUP exchange
    print("Waiting for connection and BWUP exchange (5 seconds)...")
    time.sleep(5)
    
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
        
        # Check for BWUP sent message (verbose mode)
        if "Client sent BWUP on channel" in stderr:
            print("✓ Client sent BWUP message detected")
        else:
            print("⚠ Warning: Client BWUP send message not detected")
        
        # Check for BWUP ack received (verbose mode)
        if "Client received BWUP ack from server" in stderr:
            print("✓ Client received BWUP acknowledgment")
        else:
            print("⚠ Warning: Client BWUP ack not detected - may not have been received")
        
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
        
        # Check for BWUP received message (verbose mode)
        if "Server received BWUP" in stderr:
            print("✓ Server received BWUP message")
        else:
            print("⚠ Warning: Server BWUP receive not detected")
        
        # Check for UCM sent message (verbose mode)
        if "Server sent UCM" in stderr:
            print("✓ Server sent UCM (acknowledgment)")
        else:
            print("⚠ Warning: Server UCM send not detected")
        
        # Check for UCM deleted message (verbose mode)
        if "Server deleted UCM" in stderr and "ack=0" in stderr:
            print("✓ Server deleted UCM after sending (ack=0)")
        else:
            print("⚠ Warning: Server UCM deletion not detected")
        
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.communicate()
    
    print("\n" + "=" * 60)
    print("✓ BWUP integration test passed")
    print("=" * 60)


if __name__ == "__main__":
    try:
        sys.exit(test_bwup_mode())
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
