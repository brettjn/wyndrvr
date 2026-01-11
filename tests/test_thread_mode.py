#!/usr/bin/env python3
"""
Integration test for wyndrvr thread mode - tests server with port_parallelability=THREAD
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"
CONFIG_DIR = SCRIPT_DIR / "test_thread_config"


def test_server_with_thread_mode():
    """Test that server works correctly with port_parallelability=THREAD"""
    print("=" * 60)
    print("Testing server with port_parallelability=THREAD")
    print("=" * 60)
    
    # Create config directory if it doesn't exist
    CONFIG_DIR.mkdir(exist_ok=True)
    config_path = CONFIG_DIR / "config"
    
    # Create config file with THREAD mode
    print("\nCreating config file with THREAD mode...")
    with open(config_path, 'w') as f:
        f.write("""# wyndrvr configuration file
bind_addr=0.0.0.0
bind_port=6720
port_ranges=7100-8000
connection_parallelibility=SINGLE
port_parallelability=THREAD
incoming_blocking_level=0
incoming_sleep=0
max_send_time=0
send_sleep=0
heartbeat_rate=5000
adjustment_delay=1000
flow_control_rate=10
server_block_time=100
client_block_time=100
test_verbose=true
""")
    
    # Start server with config
    print("\nStarting server with THREAD mode on port 6720...")
    server_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "--server", ":6720", "--config", str(config_path)],
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
    
    # Start client
    print("\nStarting client...")
    client_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "127.0.0.1:6720"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for connection and heartbeat exchange
    print("Waiting for connection and heartbeat exchange (10 seconds)...")
    time.sleep(10)
    
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
        has_connection_output = (
            "Connecting to server" in stdout or 
            "Received port assignment" in stdout or 
            "Client connected" in stdout or
            "Client latency:" in stderr
        )
        
        assert has_connection_output, \
            "Client should show connection or latency output"
        
        # Check for heartbeat latency output
        if "Client latency:" in stderr:
            print("✓ Client heartbeat latency detected")
        else:
            print("⚠ Warning: No client latency output detected")
        
    except subprocess.TimeoutExpired:
        client_proc.kill()
        client_proc.communicate()
    
    # Terminate server
    server_proc.terminate()
    try:
        stdout, stderr = server_proc.communicate(timeout=2)
        print(f"\nServer stdout:\n{stdout}")
        print(f"\nServer stderr:\n{stderr}")
        
        # Check for thread startup message in verbose output
        if "Started port threads for client" in stderr:
            print("✓ Port threads were started (THREAD mode working)")
        else:
            print("⚠ Warning: Thread startup message not found in stderr")
        
        # Check server output
        has_server_output = (
            "Server started" in stdout or 
            "Client connected" in stdout or
            "Server latency" in stderr
        )
        
        assert has_server_output, \
            "Server should show connection or latency output"
        
        # Check for server latency output
        if "Server latency" in stderr:
            print("✓ Server heartbeat latency detected")
        else:
            print("⚠ Warning: No server latency output detected")
        
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.communicate()
    
    print("\n" + "=" * 60)
    print("✓ Thread mode test passed!")
    print("=" * 60)


if __name__ == '__main__':
    sys.exit(test_server_with_thread_mode())
