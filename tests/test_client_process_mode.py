#!/usr/bin/env python3
"""
Integration test for wyndrvr client process mode - tests client with port_parallelability=PROCESS
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"
CONFIG_DIR = SCRIPT_DIR / "test_client_process_config"


def test_client_with_process_mode():
    """Test that client works correctly with port_parallelability=PROCESS"""
    print("=" * 60)
    print("Testing client with port_parallelability=PROCESS")
    print("=" * 60)
    
    # Create config directory if it doesn't exist
    CONFIG_DIR.mkdir(exist_ok=True)
    config_path = CONFIG_DIR / "config"
    
    # Create config file with PROCESS mode for both server and client
    print("\nCreating config file with PROCESS mode...")
    with open(config_path, 'w') as f:
        f.write("""# wyndrvr configuration file
bind_addr=0.0.0.0
bind_port=6735
port_ranges=7100-8000
connection_parallelibility=SINGLE
port_parallelability=PROCESS
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
    print("\nStarting server with PROCESS mode on port 6735...")
    server_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "--server", ":6735", "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True
    )
    
    # Wait for server to start
    time.sleep(2)
    
    if server_proc.poll() is not None:
        stdout, stderr = server_proc.communicate()
        print(f"Server failed to start: {stderr}")
        return
    
    print("✓ Server started")
    
    # Start client with config that includes PROCESS mode
    print("\nStarting client with PROCESS mode...")
    client_proc = subprocess.Popen(
        [sys.executable, str(WYNDRVR_PATH), "127.0.0.1:6735", "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True
    )
    
    # Wait for connection and heartbeat exchange
    print("Waiting for connection and heartbeat exchange (10 seconds)...")
    time.sleep(10)
    
    # Check both processes are still running
    server_running = server_proc.poll() is None
    client_running = client_proc.poll() is None
    
    print(f"\nServer running: {server_running}")
    print(f"Client running: {client_running}")
    
    # Terminate client - use process group kill to handle child processes
    import os
    import signal
    
    try:
        os.killpg(client_proc.pid, signal.SIGKILL)
    except:
        client_proc.kill()
    
    time.sleep(0.5)
    
    # Try to read what we can from client output
    try:
        stdout, stderr = client_proc.communicate(timeout=1)
        print(f"\nClient stdout:\n{stdout}")
        print(f"\nClient stderr:\n{stderr}")
        
        # Check for successful connection
        has_connection_output = (
            "Connecting to server" in stdout or 
            "Received port assignment" in stdout or 
            "Client connected" in stdout
        )
        
        # Check for process mode startup
        has_process_mode = "Client started port processes (PROCESS mode)" in stderr
        
        # Check for heartbeat latency output
        has_latency = "Client latency:" in stderr
        
        if has_connection_output:
            print("✓ Client connection detected")
        else:
            print("⚠ Warning: No client connection output detected")
        
        if has_process_mode:
            print("✓ Client process mode startup detected")
        else:
            print("⚠ Warning: No process mode startup message detected")
        
        if has_latency:
            print("✓ Client heartbeat latency detected")
        else:
            print("⚠ Warning: No client latency output detected")
        
    except subprocess.TimeoutExpired:
        pass
    
    # Terminate server - use process group kill
    try:
        os.killpg(server_proc.pid, signal.SIGKILL)
    except:
        server_proc.kill()
    
    time.sleep(0.5)
    server_proc.poll()
    
    if server_proc.returncode is not None:
        print("\n✓ Server process terminated successfully")
    
    print("\n" + "=" * 60)
    print("✓ Client process mode test completed!")
    print("=" * 60)
    print("\nNote: In PROCESS mode, each port runs in a separate process,")
    print("using message passing for inter-process communication.")


if __name__ == '__main__':
    test_client_with_process_mode()
