# Port Parallelability Thread Mode

## Quick Start

To run the wyndrvr with threaded port communication:

1. **Create/Edit Config File**
   ```bash
   ./wyndrvr.py --create-config --port-parallelability THREAD
   ```

2. **Start Server**
   ```bash
   ./wyndrvr.py --server :6711 --config ~/.config/wyndrvr/config
   ```

3. **Start Client**
   ```bash
   ./wyndrvr.py 127.0.0.1:6711 --config ~/.config/wyndrvr/config
   ```

Both server and client will use THREAD mode from the config file.

## Configuration

Set `port_parallelability=THREAD` in your config file:

```ini
# wyndrvr configuration file
bind_addr=0.0.0.0
bind_port=6711
port_ranges=7000-8000
connection_parallelibility=SINGLE
port_parallelability=THREAD  # <-- Set to THREAD
```

Or use command-line argument:
```bash
./wyndrvr.py --server :6711 --port-parallelability THREAD
```

**Note:** The `port_parallelability` setting from the config file applies to **both** server and client.

## How It Works

### Server Side
When `port_parallelability=THREAD`, each connected client gets three independent threads:

- **Thread 1**: Handles CONTROL port communication
  - Upload control messages (BWUP commands)
  - Test result messages
  - Bandwidth test timeout checks

- **Thread 2**: Handles UPLOAD port communication
  - Bandwidth test data packets
  - Flow control messages

- **Thread 3**: Handles DOWNLOAD port communication
  - Download-related communications

### Client Side
When `port_parallelability=THREAD`, the client spawns three independent threads:

- **Thread 1**: Handles CONTROL port communication
  - Control messages (BWUP acknowledgments)
  - TEST_RESULT messages and acknowledgments
  - Heartbeat responses

- **Thread 2**: Handles UPLOAD port communication
  - Bandwidth test packet transmission
  - FLOW_CONTROL message reception
  - Heartbeat responses

- **Thread 3**: Handles DOWNLOAD port communication
  - Download-related communications
  - Heartbeat responses

The main thread handles heartbeat timing and shutdown coordination.

## Benefits

- **True Parallelism**: Ports don't block each other on either server or client
- **Better Performance**: Multi-core CPU utilization
- **Improved Responsiveness**: Bursty traffic on one port doesn't affect others
- **Realistic Testing**: Simulates real-world concurrent scenarios
- **Higher Throughput**: Bandwidth tests can achieve better rates

## Thread Safety

The implementation is thread-safe:
- Each thread has its own socket (no sharing)
- Shared data structures are properly synchronized
- Clean shutdown with proper thread joining

## Testing

Run the thread mode tests:
```bash
# Test server thread mode
python3 -m pytest tests/test_thread_mode.py -v

# Test client thread mode
python3 -m pytest tests/test_client_thread_mode.py -v

# Run both thread tests
python3 -m pytest tests/ -v -k "thread"
```

Or run them standalone:
```bash
python3 tests/test_thread_mode.py
python3 tests/test_client_thread_mode.py
```

## Comparison: SINGLE vs THREAD

| Mode | Server Threads | Client Threads | Behavior | Best For |
|------|----------------|----------------|----------|----------|
| SINGLE | Main thread only | Main thread only | Sequential port polling | Simple deployments, debugging |
| THREAD | 1 main + 3 per client | 1 main + 3 for ports | Parallel port handling | Production, high traffic, multi-core |

## Verbose Mode

Enable verbose logging to see thread startup messages:

**Server:**
```bash
./wyndrvr.py --server :6711 --port-parallelability THREAD --test-verbose
```

You'll see messages like:
```
Started port threads for client 192.168.1.100:54321
```

**Client:**
```bash
./wyndrvr.py 127.0.0.1:6711 --config ~/.config/wyndrvr/config --test-verbose
```

You'll see messages like:
```
Client started port threads (THREAD mode)
```

## Implementation Details

See documentation:
- [THREAD_MODE_ARCHITECTURE.md](THREAD_MODE_ARCHITECTURE.md) - Architecture diagrams and comparisons
- Code locations:
  - Server: `ServerClientComms.port_comm_loop()` in [wyndrvr.py](wyndrvr.py)
  - Client: `WyndClient.port_comm_loop()` in [wyndrvr.py](wyndrvr.py)
