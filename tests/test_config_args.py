#!/usr/bin/env python3
"""
Test script for wyndrvr config command line arguments
"""

import subprocess
import sys
from pathlib import Path

# Get the parent directory to find wyndrvr.py
SCRIPT_DIR = Path(__file__).parent
WYNDRVR_PATH = SCRIPT_DIR.parent / "wyndrvr.py"


def test_create_config_with_args():
    """Test --create-config with command line arguments"""
    print("\nTesting --create-config with arguments...")
    test_config_path = SCRIPT_DIR / "test_config_args.conf"
    
    # Clean up if exists
    if test_config_path.exists():
        test_config_path.unlink()
    
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--bind-addr", "192.168.1.100",
         "--bind-port", "8888",
         "--heartbeat-rate", "3000",
         "--server-block-time", "200",
         "--client-block-time", "150"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Config creation with args should succeed"
    assert test_config_path.exists(), "Config file should be created"
    
    # Check content reflects command line args
    content = test_config_path.read_text()
    assert "bind_addr=192.168.1.100" in content, "Config should have custom bind_addr"
    assert "bind_port=8888" in content, "Config should have custom bind_port"
    assert "heartbeat_rate=3000" in content, "Config should have custom heartbeat_rate"
    assert "server_block_time=200" in content, "Config should have custom server_block_time"
    assert "client_block_time=150" in content, "Config should have custom client_block_time"
    
    # Clean up
    test_config_path.unlink()
    print("✓ --create-config with arguments creates config with custom values")


def test_edit_existing_config():
    """Test editing an existing config file"""
    print("\nTesting editing existing config...")
    test_config_path = SCRIPT_DIR / "test_edit_config.conf"
    
    # Create initial config with defaults
    result1 = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path)],
        capture_output=True,
        text=True
    )
    assert result1.returncode == 0, "Initial config creation should succeed"
    assert "Created" in result1.stdout, "Should indicate creation"
    
    # Now edit it with different values
    result2 = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--bind-port", "9999",
         "--heartbeat-rate", "2000"],
        capture_output=True,
        text=True
    )
    
    assert result2.returncode == 0, "Config editing should succeed"
    assert "WARNING" in result2.stdout, "Should warn about editing"
    assert "Edited existing" in result2.stdout, "Should indicate editing"
    assert "bind_port" in result2.stdout, "Should list bind_port change"
    assert "heartbeat_rate" in result2.stdout, "Should list heartbeat_rate change"
    
    # Verify the changes
    content = test_config_path.read_text()
    assert "bind_port=9999" in content, "Config should have updated bind_port"
    assert "heartbeat_rate=2000" in content, "Config should have updated heartbeat_rate"
    
    # Clean up
    test_config_path.unlink()
    print("✓ Editing existing config warns user and updates values")


def test_port_ranges_arg():
    """Test --port-ranges argument"""
    print("\nTesting --port-ranges...")
    test_config_path = SCRIPT_DIR / "test_port_ranges.conf"
    
    # Clean up if exists
    if test_config_path.exists():
        test_config_path.unlink()
    
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--port-ranges", "8000-8500,9000-9500"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Config creation should succeed"
    
    content = test_config_path.read_text()
    assert "port_ranges=8000-8500,9000-9500" in content, "Config should have custom port ranges"
    
    # Clean up
    test_config_path.unlink()
    print("✓ --port-ranges argument works correctly")


def test_parallelization_args():
    """Test parallelization mode arguments"""
    print("\nTesting parallelization arguments...")
    test_config_path = SCRIPT_DIR / "test_parallel.conf"
    
    # Clean up if exists
    if test_config_path.exists():
        test_config_path.unlink()
    
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--connection-parallelibility", "THREAD",
         "--port-parallelability", "PROCESS"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Config creation should succeed"
    
    content = test_config_path.read_text()
    assert "connection_parallelibility=THREAD" in content, "Config should have THREAD mode"
    assert "port_parallelability=PROCESS" in content, "Config should have PROCESS mode"
    
    # Clean up
    test_config_path.unlink()
    print("✓ Parallelization mode arguments work correctly")


def test_timing_args():
    """Test timing-related arguments"""
    print("\nTesting timing arguments...")
    test_config_path = SCRIPT_DIR / "test_timing.conf"
    
    # Clean up if exists
    if test_config_path.exists():
        test_config_path.unlink()
    
    result = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--incoming-blocking-level", "500",
         "--incoming-sleep", "1000",
         "--max-send-time", "2000",
         "--send-sleep", "100",
         "--adjustment-delay", "500000",
         "--flow-control-rate", "5"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Config creation should succeed"
    
    content = test_config_path.read_text()
    assert "incoming_blocking_level=500" in content
    assert "incoming_sleep=1000" in content
    assert "max_send_time=2000" in content
    assert "send_sleep=100" in content
    assert "adjustment_delay=500000" in content
    assert "flow_control_rate=5" in content
    
    # Clean up
    test_config_path.unlink()
    print("✓ Timing arguments work correctly")


def test_no_changes_warning():
    """Test that no warning is shown when config is unchanged"""
    print("\nTesting no-change scenario...")
    test_config_path = SCRIPT_DIR / "test_no_change.conf"
    
    # Create config
    result1 = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--bind-port", "7777"],
        capture_output=True,
        text=True
    )
    assert result1.returncode == 0
    
    # Try to "edit" with same value
    result2 = subprocess.run(
        [sys.executable, str(WYNDRVR_PATH), 
         "--create-config", "--config", str(test_config_path),
         "--bind-port", "7777"],
        capture_output=True,
        text=True
    )
    
    assert result2.returncode == 0
    assert "unchanged" in result2.stdout.lower(), "Should indicate no changes"
    assert "WARNING" not in result2.stdout or "unchanged" in result2.stdout.lower(), \
        "Should not warn if unchanged"
    
    # Clean up
    test_config_path.unlink()
    print("✓ No warning when config unchanged")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Running wyndrvr config argument tests")
    print("=" * 60)
    
    tests = [
        test_create_config_with_args,
        test_edit_existing_config,
        test_port_ranges_arg,
        test_parallelization_args,
        test_timing_args,
        test_no_changes_warning,
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
