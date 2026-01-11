# Thread and Process Mode Architecture

## Overview

The wyndrvr system supports three parallelization modes for port communication via the `port_parallelability` setting:
- **SINGLE**: Sequential port polling (default)
- **THREAD**: Threaded port communication
- **PROCESS**: Multi-process port communication

This enables flexible deployment options from simple single-threaded operation to full multi-process parallelism.

## SINGLE Mode (Default)

### Server
```
┌─────────────────────────────────────────────────────────┐
│ WyndServer (Main Thread)                                │
│                                                         │
│  server_comm_loop()                                     │
│    ├─ Handle new connections                           │
│    ├─ Poll Client 1 CONTROL socket                     │
│    ├─ Poll Client 1 UPLOAD socket                      │
│    ├─ Poll Client 1 DOWNLOAD socket                    │
│    ├─ Poll Client 2 CONTROL socket                     │
│    ├─ Poll Client 2 UPLOAD socket                      │
│    └─ Poll Client 2 DOWNLOAD socket                    │
│         (sequential processing)                         │
└─────────────────────────────────────────────────────────┘
```

### Client
```
┌─────────────────────────────────────────────────────────┐
│ WyndClient (Main Thread)                                │
│                                                         │
│  client_comm_loop()                                     │
│    ├─ Send heartbeats                                  │
│    ├─ Poll CONTROL socket                              │
│    ├─ Poll UPLOAD socket                               │
│    ├─ Poll DOWNLOAD socket                             │
│    └─ Send bandwidth test packets                      │
│         (sequential processing)                         │
└─────────────────────────────────────────────────────────┘
```

## THREAD Mode

### Server
```
┌─────────────────────────────────────────────────────────┐
│ WyndServer (Main Thread)                                │
│                                                         │
│  server_comm_loop()                                     │
│    └─ Handle new connections only                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
           │
           │ spawns on connect
           ▼
┌─────────────────────────────────────────────────────────┐
│ ServerClientComms for Client 1                          │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐           │
│  │ Thread 1         │  │ Thread 2         │           │
│  │ port_comm_loop   │  │ port_comm_loop   │  ...      │
│  │ (CONTROL)        │  │ (UPLOAD)         │           │
│  │                  │  │                  │           │
│  │ • Poll socket    │  │ • Poll socket    │           │
│  │ • Process data   │  │ • Process data   │           │
│  │ • Send UCM       │  │ • Send FLOW_CTL  │           │
│  │ • Check timeout  │  │                  │           │
│  └──────────────────┘  └──────────────────┘           │
│                                                         │
│  ┌──────────────────┐                                  │
│  │ Thread 3         │                                  │
│  │ port_comm_loop   │                                  │
│  │ (DOWNLOAD)       │                                  │
│  │                  │                                  │
│  │ • Poll socket    │                                  │
│  │ • Process data   │                                  │
│  └──────────────────┘                                  │
└─────────────────────────────────────────────────────────┘
```

## PROCESS Mode

### Server
```
┌─────────────────────────────────────────────────────────┐
│ WyndServer (Main Process)                               │
│                                                         │
│  server_comm_loop()                                     │
│    └─ Handle new connections only                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
           │
           │ spawns on connect
           ▼
┌─────────────────────────────────────────────────────────┐
│ ServerClientComms for Client 1                          │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐           │
│  │ Process 1        │  │ Process 2        │           │
│  │ port_comm_loop   │  │ port_comm_loop   │  ...      │
│  │ (CONTROL)        │  │ (UPLOAD)         │           │
│  │                  │  │                  │           │
│  │ • Poll socket    │  │ • Poll socket    │           │
│  │ • Process data   │  │ • Process data   │           │
│  │ • Send UCM       │  │ • Send FLOW_CTL  │           │
│  │ • Check timeout  │  │                  │           │
│  └──────────────────┘  └──────────────────┘           │
│                                                         │
│  ┌──────────────────┐                                  │
│  │ Process 3        │                                  │
│  │ port_comm_loop   │                                  │
│  │ (DOWNLOAD)       │                                  │
│  │                  │                                  │
│  │ • Poll socket    │                                  │
│  │ • Process data   │                                  │
│  └──────────────────┘                                  │
└─────────────────────────────────────────────────────────┘

Note: Each process is fully isolated with its own memory space
```

## THREAD Mode (continued)
```
┌─────────────────────────────────────────────────────────┐
│ WyndClient (Main Thread)                                │
│                                                         │
│  client_comm_loop()                                     │
│    ├─ Send heartbeats                                  │
│    ├─ Check BWUP resend                                │
│    └─ Check shutdown conditions                        │
│         (minimal, non-blocking)                         │
└─────────────────────────────────────────────────────────┘
           │
           │ spawns on start
           ▼
┌─────────────────────────────────────────────────────────┐
│ Port Threads                                            │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐           │
│  │ Thread 1         │  │ Thread 2         │           │
│  │ port_comm_loop   │  │ port_comm_loop   │  ...      │
│  │ (CONTROL)        │  │ (UPLOAD)         │           │
│  │                  │  │                  │           │
│  │ • Poll socket    │  │ • Poll socket    │           │
│  │ • Handle CONTROL │  │ • Handle BW test │           │
│  │ • Handle TEST    │  │ • Handle FLOW    │           │
│  │   RESULT         │  │   CONTROL        │           │
│  │ • Send heartbeat │  │ • Send BW pkts   │           │
│  │   replies        │  │ • Send heartbeat │           │
│  │                  │  │   replies        │           │
│  └──────────────────┘  └──────────────────┘           │
│                                                         │
│  ┌──────────────────┐                                  │
│  │ Thread 3         │                                  │
│  │ port_comm_loop   │                                  │
│  │ (DOWNLOAD)       │                                  │
│  │                  │                                  │
│  │ • Poll socket    │                                  │
│  │ • Handle msgs    │                                  │
│  │ • Send heartbeat │                                  │
│  │   replies        │                                  │
│  └──────────────────┘                                  │
└─────────────────────────────────────────────────────────┘
```

## Key Differences

| Aspect | SINGLE Mode | THREAD Mode | PROCESS Mode |
|--------|-------------|-------------|--------------|
| **Server Port Processing** | Sequential | Parallel (threads) | Parallel (processes) |
| **Client Port Processing** | Sequential | Parallel (threads) | N/A |
| **Main Loop Role (Server)** | Polls all sockets | Handles new connections | Handles new connections |
| **Main Loop Role (Client)** | Polls all sockets | Minimal (heartbeat timing) | N/A |
| **Workers per Client (Server)** | 0 | 3 threads | 3 processes |
| **Workers per Client Instance** | 0 | 3 threads | N/A |
| **Memory Isolation** | Shared | Shared | Isolated per process |
| **CPU Utilization** | Single core | Multi-core | Multi-core |
| **Port Independence** | Blocked by others | Fully independent | Fully independent |
| **Overhead** | Minimal | Thread management | Process management |
| **GIL Impact** | N/A | Subject to GIL | No GIL (separate processes) |

## When to Use Each Mode

### Use SINGLE Mode When:
- Running on single-core systems
- Handling few clients with light traffic
- Minimizing system overhead is critical
- Simpler debugging is preferred
- Testing basic functionality

### Use THREAD Mode When:
- Running on multi-core systems
- Handling multiple clients with moderate traffic
- Port-level parallelism is beneficial
- Lower memory overhead is important
- I/O-bound workloads (network communication)
- Client needs parallel port handling

### Use PROCESS Mode When:
- Running on multi-core systems with heavy CPU usage
- Maximum isolation between port handlers is required
- CPU-bound processing on each port
- Avoiding Python GIL limitations is critical
- Maximum reliability (process crash doesn't affect others)
- Heavy bandwidth testing scenarios

## Configuration

Set `port_parallelability=THREAD` in your config file:

```ini
# wyndrvr configuration file
port_parallelability=THREAD
```

This setting affects **both** the server and client:
- **Server**: Creates 3 threads per connected client for port handling
- **Client**: Creates 3 threads for its own port communication

Both server and client can independently benefit from thread mode.

## Implementation Notes

### Thread Safety
- Each thread has its own socket (no sharing)
- Shared data structures use proper synchronization
- Clean shutdown with proper thread joining
- Timeout-based thread termination (1.0 second)

### Thread Lifecycle

**Server:**
1. Client connects → ServerClientComms created
2. `start_port_threads()` called → 3 threads spawn
3. Each thread runs `port_comm_loop(port_type)`
4. On disconnect → `stop_port_threads()` → threads join → sockets close

**Client:**
1. Connection established → ports assigned
2. `start_port_threads()` called → 3 threads spawn
3. Each thread runs `port_comm_loop(port_type)`
4. On shutdown → `stop_port_threads()` → threads join → sockets close
