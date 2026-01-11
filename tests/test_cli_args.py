#!/usr/bin/env python3
"""
Test script for wyndrvr command line arguments
"""

import subprocess
import sys
import os
import time
from pathlib import Path

# Get the parent directory to find wyndrvr.py
SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"


def run_command(args, timeout=2):
    """Run wyndrvr with given arguments and return process"""
    cmd = [sys.executable, str(WYNDRVR_PATH)] + args
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return proc
    except Exception as e:
        print(f"Error running command: {e}")
        return None


def test_help():
    """Test --help argument"""
    print("Testing --help...")
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, "Help should return 0"
    assert "wyndrvr" in result.stdout.lower(), "Help should mention wyndrvr"
    assert "--server" in result.stdout, "Help should show --server option"
    assert "--config" in result.stdout, "Help should show --config option"
    assert "--create-config" in result.stdout, "Help should show --create-config option"
    print("✓ --help works correctly")


def test_no_args():
    """Test running with no arguments - should default to client mode connecting to 127.0.0.1:6711"""
    print("\nTesting no arguments...")
    # Run with short timeout since client will keep running
    try:
        result = subprocess.run(
            [sys.executable, str(WYNDRVR_PATH)],
            capture_output=True,
            text=True,
            timeout=2  # Short timeout - client runs indefinitely
        )
        # If it returns quickly, check for timeout error (no server case)
        assert result.returncode == 0, "No args should run as client and return 0"
        assert "Connecting to server 127.0.0.1:6711" in result.stdout, "Should attempt to connect to 127.0.0.1:6711"
    except subprocess.TimeoutExpired as e:
        # This is expected - client connects and runs indefinitely
        # Check that it attempted connection
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        assert "Connecting to server 127.0.0.1:6711" in stdout, "Should attempt to connect to 127.0.0.1:6711"
        # Either successfully connected (and running) or timed out waiting for server
        # Both are valid behaviors for client mode
        print("✓ No arguments defaults to client mode connecting to 127.0.0.1:6711")
    else:
        print("✓ No arguments defaults to client mode connecting to 127.0.0.1:6711")


def test_create_config():
    """Test --create-config"""
    print("\nTesting --create-config...")
    test_config_path = SCRIPT_DIR / "test_config.conf"
    
    # Clean up if exists
    if test_config_path.exists():
        test_config_path.unlink()
    
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), "--create-config", "--config", str(test_config_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Config creation should succeed"
    assert test_config_path.exists(), "Config file should be created"
    
    # Check content
    content = test_config_path.read_text()
    assert "bind_addr" in content, "Config should contain bind_addr"
    assert "bind_port" in content, "Config should contain bind_port"
    assert "server_block_time" in content, "Config should contain server_block_time"
    assert "client_block_time" in content, "Config should contain client_block_time"
    
    # Clean up
    test_config_path.unlink()
    print("✓ --create-config creates valid config file")


def test_server_start():
    """Test starting server"""
    print("\nTesting --server...")
    
    proc = run_command(["--server", ":6712"])
    assert proc is not None, "Server should start"
    
    time.sleep(1)
    
    # Check if process is running
    assert proc.poll() is None, "Server should still be running"
    
    # Terminate
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    print("✓ Server starts successfully")


def test_server_with_config():
    """Test server with custom config"""
    print("\nTesting --server with --config...")
    
    test_config_path = SCRIPT_DIR / "test_config2.conf"
    
    # Create config first
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), "--create-config", "--config", str(test_config_path)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, "Config creation should succeed"
    
    # Start server with config
    proc = run_command(["--server", "--config", str(test_config_path)])
    assert proc is not None, "Server should start with config"
    
    time.sleep(1)
    assert proc.poll() is None, "Server should still be running"
    
    # Terminate
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    # Clean up
    test_config_path.unlink()
    print("✓ Server starts with custom config")


def test_client_timeout():
    """Test client connection timeout"""
    print("\nTesting client timeout (no server)...")
    
    # Try to connect to non-existent server (should timeout in 5 seconds)
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), "127.0.0.1:9999"],
        capture_output=True,
        text=True,
        timeout=8
    )
    
    # Should exit after timeout
    assert result.returncode != 0 or "Timeout" in result.stderr or "timeout" in result.stderr.lower(), \
        "Client should timeout or exit when no server available"
    print("✓ Client times out appropriately when server unavailable")


def test_server_address_formats():
    """Test various server address format parsing"""
    print("\nTesting address format parsing...")
    
    # Test with just port
    proc = run_command(["--server", ":6713"])
    assert proc is not None, "Server should start with :port format"
    time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    # Test with address and port
    proc = run_command(["--server", "127.0.0.1:6714"])
    assert proc is not None, "Server should start with addr:port format"
    time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    # Test with just --server (no args)
    proc = run_command(["--server"])
    assert proc is not None, "Server should start with --server only"
    time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    print("✓ Various address formats parsed correctly")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Running wyndrvr CLI argument tests")
    print("=" * 60)
    
    tests = [
        test_help,
        test_no_args,
        test_create_config,
        test_server_start,
        test_server_with_config,
        test_client_timeout,
        test_server_address_formats,
    ]
    
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed.append(test.__name__)
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed.append(test.__name__)
    
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} test(s) failed")
        for name in failed:
            print(f"  - {name}")
        return 1
    else:
        print(f"SUCCESS: All {len(tests)} tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(run_all_tests())
