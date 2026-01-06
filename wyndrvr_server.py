#!/usr/bin/env python3
"""
Wyndrvr Server - Network Bandwidth and Latency Testing Server

This server handles incoming connections from clients and responds to:
- Latency test requests (echo back small messages)
- Bandwidth test requests (send/receive large chunks of data)

Supports both threading and multiprocessing for handling concurrent connections.
"""

import socket
import threading
import argparse
import time
import sys
from multiprocessing import Process


class WyndrvrServer:
    """Server for network bandwidth and latency testing."""
    
    def __init__(self, host='0.0.0.0', port=5001, mode='thread'):
        """
        Initialize the server.
        
        Args:
            host: Host address to bind to
            port: Port number to listen on
            mode: Connection handling mode ('thread' or 'process')
        """
        self.host = host
        self.port = port
        self.mode = mode
        self.running = False
        self.socket = None
        
    def start(self):
        """Start the server and listen for connections."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.running = True
            
            print(f"[SERVER] Wyndrvr server started on {self.host}:{self.port}")
            print(f"[SERVER] Connection handling mode: {self.mode}")
            print("[SERVER] Waiting for connections...")
            
            while self.running:
                try:
                    client_socket, address = self.socket.accept()
                    print(f"[SERVER] Connection from {address}")
                    
                    if self.mode == 'thread':
                        handler = threading.Thread(
                            target=self.handle_client,
                            args=(client_socket, address)
                        )
                        handler.daemon = True
                        handler.start()
                    elif self.mode == 'process':
                        handler = Process(
                            target=self.handle_client,
                            args=(client_socket, address)
                        )
                        handler.daemon = True
                        handler.start()
                    else:
                        self.handle_client(client_socket, address)
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[SERVER] Error accepting connection: {e}")
                    
        except Exception as e:
            print(f"[SERVER] Error starting server: {e}")
            sys.exit(1)
        finally:
            self.stop()
            
    def handle_client(self, client_socket, address):
        """
        Handle a client connection.
        
        Args:
            client_socket: Client socket object
            address: Client address tuple
        """
        try:
            while True:
                # Receive command from client
                data = client_socket.recv(1024).decode('utf-8').strip()
                
                if not data:
                    break
                    
                if data == 'PING':
                    # Latency test - echo back immediately
                    client_socket.sendall(b'PONG')
                    
                elif data.startswith('BANDWIDTH_DOWNLOAD'):
                    # Bandwidth test - send data to client
                    try:
                        # Parse size from command: BANDWIDTH_DOWNLOAD:size
                        size = int(data.split(':')[1])
                        self.send_bandwidth_data(client_socket, size)
                    except (IndexError, ValueError):
                        client_socket.sendall(b'ERROR:Invalid command format')
                        
                elif data.startswith('BANDWIDTH_UPLOAD'):
                    # Bandwidth test - receive data from client
                    try:
                        # Parse size from command: BANDWIDTH_UPLOAD:size
                        size = int(data.split(':')[1])
                        self.receive_bandwidth_data(client_socket, size)
                    except (IndexError, ValueError):
                        client_socket.sendall(b'ERROR:Invalid command format')
                        
                elif data == 'QUIT':
                    client_socket.sendall(b'BYE')
                    break
                    
                else:
                    client_socket.sendall(b'ERROR:Unknown command')
                    
        except Exception as e:
            print(f"[SERVER] Error handling client {address}: {e}")
        finally:
            client_socket.close()
            print(f"[SERVER] Connection closed: {address}")
            
    def send_bandwidth_data(self, client_socket, size):
        """
        Send data to client for download bandwidth test.
        
        Args:
            client_socket: Client socket object
            size: Amount of data to send in bytes
        """
        try:
            # Send acknowledgment
            client_socket.sendall(b'READY')
            
            # Generate and send data in chunks
            chunk_size = 65536  # 64 KB chunks
            sent = 0
            data_chunk = b'x' * chunk_size
            
            while sent < size:
                remaining = size - sent
                to_send = min(chunk_size, remaining)
                
                if to_send < chunk_size:
                    data_chunk = b'x' * to_send
                    
                client_socket.sendall(data_chunk)
                sent += to_send
                
            print(f"[SERVER] Sent {sent} bytes for bandwidth test")
            
        except Exception as e:
            print(f"[SERVER] Error sending bandwidth data: {e}")
            
    def receive_bandwidth_data(self, client_socket, size):
        """
        Receive data from client for upload bandwidth test.
        
        Args:
            client_socket: Client socket object
            size: Amount of data to receive in bytes
        """
        try:
            # Send acknowledgment
            client_socket.sendall(b'READY')
            
            # Receive data
            received = 0
            
            while received < size:
                data = client_socket.recv(65536)
                if not data:
                    break
                received += len(data)
                
            print(f"[SERVER] Received {received} bytes for bandwidth test")
            
            # Send completion acknowledgment
            client_socket.sendall(b'DONE')
            
        except Exception as e:
            print(f"[SERVER] Error receiving bandwidth data: {e}")
            
    def stop(self):
        """Stop the server."""
        self.running = False
        if self.socket:
            self.socket.close()
        print("[SERVER] Server stopped")


def main():
    """Main entry point for the server."""
    parser = argparse.ArgumentParser(
        description='Wyndrvr Server - Network Bandwidth and Latency Testing'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host address to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5001,
        help='Port number to listen on (default: 5001)'
    )
    parser.add_argument(
        '--mode',
        choices=['thread', 'process', 'sequential'],
        default='thread',
        help='Connection handling mode (default: thread)'
    )
    
    args = parser.parse_args()
    
    server = WyndrvrServer(host=args.host, port=args.port, mode=args.mode)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        server.stop()


if __name__ == '__main__':
    main()
