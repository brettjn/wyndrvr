#!/usr/bin/env python3
"""
Example test script demonstrating the wyndrvr utility.

This script shows how to programmatically use the client and server.
For command-line usage, see the README.md file.
"""

import time
import subprocess
import sys
from pathlib import Path


def run_demo():
    """Run a demonstration of the wyndrvr utility."""
    print("="*70)
    print("WYNDRVR DEMONSTRATION")
    print("="*70)
    print()
    print("This demo will:")
    print("1. Start a server in the background")
    print("2. Run various client tests")
    print("3. Show the capabilities of processes, threads, and sockets")
    print()
    print("="*70)
    print()
    
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    server_script = script_dir / "wyndrvr_server.py"
    client_script = script_dir / "wyndrvr_client.py"
    
    # Start the server
    print("[DEMO] Starting server on localhost:5001...")
    server_process = subprocess.Popen(
        [sys.executable, str(server_script), "--host", "127.0.0.1", "--port", "5001"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Give server time to start
    time.sleep(2)
    
    try:
        # Test 1: Latency
        print("\n" + "="*70)
        print("TEST 1: LATENCY TEST")
        print("="*70)
        result = subprocess.run(
            [sys.executable, str(client_script), "--host", "127.0.0.1", 
             "--port", "5001", "--test", "latency", "--count", "5"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Test 2: Download bandwidth
        print("\n" + "="*70)
        print("TEST 2: DOWNLOAD BANDWIDTH TEST")
        print("="*70)
        result = subprocess.run(
            [sys.executable, str(client_script), "--host", "127.0.0.1",
             "--port", "5001", "--test", "download", "--size", "5"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Test 3: Upload bandwidth
        print("\n" + "="*70)
        print("TEST 3: UPLOAD BANDWIDTH TEST")
        print("="*70)
        result = subprocess.run(
            [sys.executable, str(client_script), "--host", "127.0.0.1",
             "--port", "5001", "--test", "upload", "--size", "5"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Test 4: Concurrent clients (demonstrates threading)
        print("\n" + "="*70)
        print("TEST 4: CONCURRENT CLIENTS (Threading Demo)")
        print("="*70)
        result = subprocess.run(
            [sys.executable, str(client_script), "--host", "127.0.0.1",
             "--port", "5001", "--concurrent", "3"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Test 5: Full test suite
        print("\n" + "="*70)
        print("TEST 5: COMPLETE TEST SUITE")
        print("="*70)
        result = subprocess.run(
            [sys.executable, str(client_script), "--host", "127.0.0.1",
             "--port", "5001", "--count", "5", "--size", "3"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
    finally:
        # Stop the server
        print("\n" + "="*70)
        print("[DEMO] Stopping server...")
        server_process.terminate()
        server_process.wait(timeout=5)
        print("[DEMO] Server stopped")
        print("="*70)
        
    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)
    print()
    print("Key concepts demonstrated:")
    print("  ✓ Socket programming (TCP client-server)")
    print("  ✓ Threading (server handling multiple clients, concurrent client tests)")
    print("  ✓ Processes (server can use process-based concurrency)")
    print("  ✓ Network performance measurement (latency & bandwidth)")
    print()
    print("For more options, run:")
    print(f"  python {server_script} --help")
    print(f"  python {client_script} --help")
    print()


if __name__ == '__main__':
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\n[DEMO] Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n[DEMO] Error: {e}")
        sys.exit(1)
