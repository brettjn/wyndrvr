# wyndrvr Tests

This directory contains test scripts for wyndrvr.

## Test Files

### test_cli_args.py
Tests command line argument parsing and basic functionality:
- `--help` option
- No arguments (should show usage)
- `--create-config` option
- `--server` option with various address formats
- `--config` option
- Client timeout when no server available

Run with:
```bash
python3 test_cli_args.py
```

### test_integration.py
Integration test that starts both a server and client to verify:
- Server starts successfully
- Client connects to server
- Port assignments work
- Heartbeat exchange occurs
- Latency measurements are reported

Run with:
```bash
python3 test_integration.py
```

### test_config_args.py
Tests configuration command line arguments:
- Creating config with custom values via CLI args
- Editing existing config files
- Warning messages when editing existing files
- All config settings (bind-addr, bind-port, port-ranges, etc.)
- Parallelization mode arguments
- Timing-related arguments
- No warning when values unchanged

Run with:
```bash
python3 test_config_args.py
```

## Running All Tests

To run all tests:
```bash
python3 test_cli_args.py && python3 test_integration.py && python3 test_config_args.py
```

## Requirements

Tests require Python 3.6+ and use only standard library modules.
