# Client PROCESS Mode Implementation Summary

## Overview
Implemented separate process handling for client-side wyndrvr operations when `port_parallelability` is set to `PROCESS`. Each of the three ports (control, upload, download) now runs in its own process with inter-process communication via message passing.

## Key Changes

### 1. Added Multiprocessing Support Attributes (`__init__`)
- `port_processes`: List to track spawned processes
- `shared_manager`: Multiprocessing Manager for shared state
- `shared_bwup_acked`: Shared flag for bandwidth upload acknowledgment
- `shared_bw_test_start_time`: Shared timestamp for bandwidth test start
- `shared_test_result_received`: Shared timestamp for TEST_RESULT receipt
- `shared_test_result_data`: Shared dictionary for TEST_RESULT data
- `shared_test_result_guid`: Shared list for TEST_RESULT GUID
- `shared_working_sequence_span_data`: Shared list for sequence span data
- `shared_flow_control_buffer`: Shared list for flow control buffer

### 2. Process Management Methods

#### `start_port_processes()`
- Creates a multiprocessing.Manager() for shared state management
- Initializes all shared state variables using Manager primitives
- Spawns three daemon processes (one per port type)
- Each process runs `port_comm_loop()` with its assigned port type

#### `stop_port_processes()`
- Terminates all spawned processes gracefully
- Force-kills processes that don't terminate within timeout
- Properly shuts down the multiprocessing Manager
- Cleans up process list

### 3. Shared State Helper Methods
Created helper methods to abstract access to shared vs. local state:
- `_get_bwup_acked()` / `_set_bwup_acked()`
- `_get_bw_test_start_time()` / `_set_bw_test_start_time()`
- `_get_test_result_received()` / `_set_test_result_received()`
- `_set_test_result_data()` / `_set_test_result_guid()`
- `_get_working_sequence_span()` / `_set_working_sequence_span()`

These methods automatically use shared state when in PROCESS mode, otherwise use local instance variables.

### 4. Updated Core Methods

#### `client_comm_loop()`
Added PROCESS mode branch similar to existing THREAD mode:
- Starts port processes via `start_port_processes()`
- Minimal main loop that coordinates via shared state
- Handles heartbeat timing in main process
- Checks shared state for BWUP acknowledgment and TEST_RESULT receipt
- Coordinates shutdown across processes

#### `port_comm_loop()`
Updated to use helper methods for state access:
- Calls `_get_test_result_received()` instead of direct access
- Calls `_set_bwup_acked()` / `_set_bw_test_start_time()` when receiving BWUP ack
- Updates shared state when receiving TEST_RESULT

#### `_handle_flow_control_message()`
- Uses `_get_working_sequence_span()` / `_set_working_sequence_span()`
- Properly synchronizes span updates across processes

#### `send_bandwidth_test_packets()`
- Uses `_get_bw_test_start_time()` / `_get_working_sequence_span()`
- Updates shared sequence span after sending packets
- Ensures all processes see consistent sequence state

#### `stop()`
- Added call to `stop_port_processes()` if processes exist
- Ensures proper cleanup on client shutdown

## Message Passing Strategy

Uses Python's `multiprocessing.Manager` for inter-process communication:
- **Manager.Value**: For atomic numeric values (bools as ints, floats)
- **Manager.dict**: For structured data (TEST_RESULT payload)
- **Manager.list**: For sequence data structures (spans, GUIDs, buffers)

No shared memory is used - all communication goes through the Manager's proxy objects which handle serialization and synchronization automatically.

## Testing

Created `test_client_process_mode.py` to verify:
- Client successfully starts with PROCESS mode
- All three port processes are spawned
- Heartbeat exchange works on all ports
- Processes can be cleanly terminated

Test results show:
```
Client started port processes (PROCESS mode)
Client latency CONTROL  : 18.82 ms
Client latency UPLOAD   : 20.48 ms
Client latency DOWNLOAD : 20.36 ms
```

This confirms all three ports are running in separate processes and communicating properly.

## Benefits

1. **True Parallelism**: Each port operates in its own process with separate Python interpreter
2. **No GIL Contention**: Python's Global Interpreter Lock doesn't restrict parallelism
3. **Fault Isolation**: If one port process crashes, others can continue
4. **Resource Distribution**: OS can schedule port processes on different CPU cores
5. **Consistency**: Implementation mirrors existing server-side PROCESS mode pattern

## Compatibility

- Fully backward compatible - only activates when `port_parallelability=PROCESS`
- Works with existing SINGLE and THREAD modes unchanged
- Compatible with bandwidth tests (--bwup flag)
- Integrates with flow control and test result mechanisms
