# wyndrvr
Latency and Bandwidth Utility

A Python-based network testing tool for measuring bandwidth and latency. This utility demonstrates the use of processes, threads, and sockets for network performance testing.

## Features

- **Latency Testing**: Measure round-trip time with ping-like functionality
- **Bandwidth Testing**: Test upload and download speeds
- **Concurrent Connections**: Server handles multiple clients using threads or processes
- **Flexible Testing**: Run individual tests or comprehensive test suites
- **Statistics**: Detailed metrics including min, max, average, and standard deviation

## Components

### Server (`wyndrvr_server.py`)
The server listens for client connections and responds to test requests. It supports three modes:
- **Thread mode**: Handle each connection in a separate thread (default)
- **Process mode**: Handle each connection in a separate process
- **Sequential mode**: Handle connections one at a time

### Client (`wyndrvr_client.py`)
The client connects to the server and performs various network tests:
- Latency tests (PING/PONG)
- Download bandwidth tests
- Upload bandwidth tests
- Concurrent client testing using threads

## Installation

No external dependencies required! Uses only Python standard library.

```bash
# Clone the repository
git clone https://github.com/brettjn/wyndrvr.git
cd wyndrvr

# Make scripts executable (optional)
chmod +x wyndrvr_server.py wyndrvr_client.py
```

## Quick Start

Try the automated demo that showcases all features:

```bash
python example_test.py
```

This will automatically:
1. Start a server in the background
2. Run various client tests (latency, download, upload, concurrent)
3. Display comprehensive results
4. Clean up automatically

## Usage

### Starting the Server

Basic server startup (listens on all interfaces, port 5001):
```bash
python wyndrvr_server.py
```

Custom host and port:
```bash
python wyndrvr_server.py --host 0.0.0.0 --port 8080
```

Use process-based concurrency instead of threads:
```bash
python wyndrvr_server.py --mode process
```

Available modes:
- `thread` - Use threads for concurrent connections (default)
- `process` - Use processes for concurrent connections
- `sequential` - Handle one connection at a time

### Running Client Tests

Run all tests (latency, download, upload):
```bash
python wyndrvr_client.py --host localhost --port 5001
```

Run only latency test:
```bash
python wyndrvr_client.py --test latency --count 20
```

Run only download bandwidth test:
```bash
python wyndrvr_client.py --test download --size 50
```

Run only upload bandwidth test:
```bash
python wyndrvr_client.py --test upload --size 25
```

Run concurrent clients (demonstrates threading):
```bash
python wyndrvr_client.py --concurrent 5
```

### Complete Example Session

Terminal 1 (Server):
```bash
$ python wyndrvr_server.py
[SERVER] Wyndrvr server started on 0.0.0.0:5001
[SERVER] Connection handling mode: thread
[SERVER] Waiting for connections...
```

Terminal 2 (Client):
```bash
$ python wyndrvr_client.py
[CLIENT] Connected to localhost:5001

============================================================
WYNDRVR NETWORK TEST SUITE
============================================================

[CLIENT] Starting latency test (10 pings)...
  Ping 1/10: 0.25 ms
  Ping 2/10: 0.18 ms
  ...
  
[CLIENT] Latency Statistics:
  Packets sent: 10
  Packets received: 10
  Minimum: 0.15 ms
  Maximum: 0.35 ms
  Average: 0.22 ms
  Std Dev: 0.05 ms

[CLIENT] Starting download bandwidth test (10 MB)...
[CLIENT] Downloaded 10.00 MB in 0.15 seconds
[CLIENT] Download speed: 533.33 Mbps

[CLIENT] Starting upload bandwidth test (10 MB)...
[CLIENT] Uploaded 10.00 MB in 0.18 seconds
[CLIENT] Upload speed: 444.44 Mbps

============================================================
TEST SUMMARY
============================================================
Average Latency: 0.22 ms
Download Speed: 533.33 Mbps
Upload Speed: 444.44 Mbps
============================================================
```

## Command Line Options

### Server Options
```
--host HOST          Host address to bind to (default: 0.0.0.0)
--port PORT          Port number to listen on (default: 5001)
--mode MODE          Connection handling mode: thread, process, or sequential (default: thread)
```

### Client Options
```
--host HOST          Server host address (default: localhost)
--port PORT          Server port number (default: 5001)
--test TEST          Test to run: latency, download, upload, or all (default: all)
--count COUNT        Number of latency tests (default: 10)
--size SIZE          Size for bandwidth tests in MB (default: 10)
--concurrent N       Run N concurrent clients using threads
```

## Architecture

### Socket Programming
- Uses TCP sockets for reliable communication
- Server binds to specified host:port
- Clients connect and send commands

### Threading
- Server: Each client connection handled in a separate thread (thread mode)
- Client: Concurrent mode spawns multiple client threads

### Process-based Concurrency
- Server: Can use multiprocessing module to handle connections (process mode)
- Each connection runs in an isolated process

### Protocol
Simple text-based protocol:
- `PING` → `PONG` (latency test)
- `BANDWIDTH_DOWNLOAD:size` → sends specified bytes
- `BANDWIDTH_UPLOAD:size` → receives specified bytes
- `QUIT` → `BYE` (disconnect)

## Technical Concepts Demonstrated

This project demonstrates several important networking and concurrency concepts:

### 1. Socket Programming
- **TCP Sockets**: Reliable, connection-oriented communication
- **Server Socket**: Binds to address/port and listens for connections
- **Client Socket**: Connects to server and exchanges data
- **Binary Protocol**: Simple text-based commands (PING, BANDWIDTH_DOWNLOAD, etc.)

### 2. Threading
- **Server Threading**: Each client connection runs in a separate thread
  - Allows multiple clients to connect simultaneously
  - Shared resources between threads (socket handlers)
  - Daemon threads for automatic cleanup
- **Client Threading**: Concurrent testing mode spawns multiple client threads
  - Demonstrates parallel network operations
  - Thread-safe result collection with locks

### 3. Multiprocessing
- **Process-based Server**: Alternative to threading using separate processes
  - Each client connection handled by dedicated process
  - Process isolation (separate memory space)
  - Better for CPU-bound operations
  - Demonstrates both threading and process-based concurrency

### 4. Network Performance Metrics
- **Latency (RTT)**: Round-trip time measurement using PING/PONG
- **Bandwidth**: Data transfer rate in Mbps (upload and download)
- **Statistical Analysis**: Min, max, average, standard deviation

## Requirements

- Python 3.6 or higher
- No external dependencies

## Testing

The implementation uses Python's standard library exclusively, so no additional setup is needed. To test:

1. Start the server in one terminal
2. Run various client tests in other terminals
3. Try concurrent clients to see threading in action
4. Switch server modes to compare thread vs process handling

Or simply run the automated demo:
```bash
python example_test.py
```

## License

See LICENSE file for details.
