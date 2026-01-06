#!/usr/bin/env python3
"""
Wyndrvr Client - Network Bandwidth and Latency Testing Client

This client connects to a Wyndrvr server and performs:
- Latency tests (measures round-trip time)
- Bandwidth tests (measures upload and download speeds)

Supports concurrent testing using threads.
"""

import socket
import argparse
import time
import sys
import threading
from statistics import mean, stdev


class WyndrvrClient:
    """Client for network bandwidth and latency testing."""
    
    def __init__(self, host='localhost', port=5001):
        """
        Initialize the client.
        
        Args:
            host: Server host address
            port: Server port number
        """
        self.host = host
        self.port = port
        self.socket = None
        
    def connect(self):
        """Connect to the server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            print(f"[CLIENT] Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[CLIENT] Failed to connect: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from the server."""
        if self.socket:
            try:
                self.socket.sendall(b'QUIT')
                response = self.socket.recv(1024)
                print(f"[CLIENT] Server response: {response.decode('utf-8')}")
            except:
                pass
            finally:
                self.socket.close()
                print("[CLIENT] Disconnected")
                
    def test_latency(self, count=10):
        """
        Test network latency.
        
        Args:
            count: Number of ping tests to perform
            
        Returns:
            Dictionary with latency statistics
        """
        print(f"\n[CLIENT] Starting latency test ({count} pings)...")
        latencies = []
        
        for i in range(count):
            try:
                start_time = time.time()
                self.socket.sendall(b'PING')
                response = self.socket.recv(1024)
                end_time = time.time()
                
                if response == b'PONG':
                    latency_ms = (end_time - start_time) * 1000
                    latencies.append(latency_ms)
                    print(f"  Ping {i+1}/{count}: {latency_ms:.2f} ms")
                else:
                    print(f"  Ping {i+1}/{count}: Invalid response")
                    
                # Small delay between pings
                time.sleep(0.1)
                
            except Exception as e:
                print(f"  Ping {i+1}/{count}: Error - {e}")
                
        if latencies:
            stats = {
                'count': len(latencies),
                'min': min(latencies),
                'max': max(latencies),
                'avg': mean(latencies),
                'stdev': stdev(latencies) if len(latencies) > 1 else 0
            }
            
            print(f"\n[CLIENT] Latency Statistics:")
            print(f"  Packets sent: {count}")
            print(f"  Packets received: {stats['count']}")
            print(f"  Minimum: {stats['min']:.2f} ms")
            print(f"  Maximum: {stats['max']:.2f} ms")
            print(f"  Average: {stats['avg']:.2f} ms")
            print(f"  Std Dev: {stats['stdev']:.2f} ms")
            
            return stats
        else:
            print("[CLIENT] No successful pings")
            return None
            
    def test_bandwidth_download(self, size_mb=10):
        """
        Test download bandwidth.
        
        Args:
            size_mb: Size of data to download in megabytes
            
        Returns:
            Download speed in Mbps
        """
        print(f"\n[CLIENT] Starting download bandwidth test ({size_mb} MB)...")
        
        size_bytes = size_mb * 1024 * 1024
        
        try:
            # Send download request
            command = f'BANDWIDTH_DOWNLOAD:{size_bytes}'.encode('utf-8')
            self.socket.sendall(command)
            
            # Wait for ready signal
            response = self.socket.recv(1024)
            if response != b'READY':
                print(f"[CLIENT] Server not ready: {response}")
                return None
                
            # Receive data and measure time
            received = 0
            start_time = time.time()
            
            while received < size_bytes:
                data = self.socket.recv(65536)
                if not data:
                    break
                received += len(data)
                
            end_time = time.time()
            duration = end_time - start_time
            
            # Calculate speed
            speed_mbps = (received * 8) / (duration * 1000000)
            
            print(f"[CLIENT] Downloaded {received / (1024*1024):.2f} MB in {duration:.2f} seconds")
            print(f"[CLIENT] Download speed: {speed_mbps:.2f} Mbps")
            
            return speed_mbps
            
        except Exception as e:
            print(f"[CLIENT] Error during download test: {e}")
            return None
            
    def test_bandwidth_upload(self, size_mb=10):
        """
        Test upload bandwidth.
        
        Args:
            size_mb: Size of data to upload in megabytes
            
        Returns:
            Upload speed in Mbps
        """
        print(f"\n[CLIENT] Starting upload bandwidth test ({size_mb} MB)...")
        
        size_bytes = size_mb * 1024 * 1024
        
        try:
            # Send upload request
            command = f'BANDWIDTH_UPLOAD:{size_bytes}'.encode('utf-8')
            self.socket.sendall(command)
            
            # Wait for ready signal
            response = self.socket.recv(1024)
            if response != b'READY':
                print(f"[CLIENT] Server not ready: {response}")
                return None
                
            # Send data and measure time
            chunk_size = 65536  # 64 KB chunks
            sent = 0
            data_chunk = b'x' * chunk_size
            start_time = time.time()
            
            while sent < size_bytes:
                remaining = size_bytes - sent
                to_send = min(chunk_size, remaining)
                
                if to_send < chunk_size:
                    data_chunk = b'x' * to_send
                    
                self.socket.sendall(data_chunk)
                sent += to_send
                
            end_time = time.time()
            
            # Wait for completion acknowledgment
            response = self.socket.recv(1024)
            
            duration = end_time - start_time
            
            # Calculate speed
            speed_mbps = (sent * 8) / (duration * 1000000)
            
            print(f"[CLIENT] Uploaded {sent / (1024*1024):.2f} MB in {duration:.2f} seconds")
            print(f"[CLIENT] Upload speed: {speed_mbps:.2f} Mbps")
            
            return speed_mbps
            
        except Exception as e:
            print(f"[CLIENT] Error during upload test: {e}")
            return None
            
    def run_all_tests(self, latency_count=10, bandwidth_size_mb=10):
        """
        Run all tests: latency, download, and upload.
        
        Args:
            latency_count: Number of latency tests
            bandwidth_size_mb: Size for bandwidth tests in MB
        """
        print("\n" + "="*60)
        print("WYNDRVR NETWORK TEST SUITE")
        print("="*60)
        
        # Test latency
        latency_stats = self.test_latency(count=latency_count)
        
        # Test download bandwidth
        download_speed = self.test_bandwidth_download(size_mb=bandwidth_size_mb)
        
        # Test upload bandwidth
        upload_speed = self.test_bandwidth_upload(size_mb=bandwidth_size_mb)
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        if latency_stats:
            print(f"Average Latency: {latency_stats['avg']:.2f} ms")
        else:
            print("Average Latency: N/A")
            
        if download_speed:
            print(f"Download Speed: {download_speed:.2f} Mbps")
        else:
            print("Download Speed: N/A")
            
        if upload_speed:
            print(f"Upload Speed: {upload_speed:.2f} Mbps")
        else:
            print("Upload Speed: N/A")
            
        print("="*60)


class ConcurrentTester:
    """Run multiple concurrent client tests using threads."""
    
    def __init__(self, host, port, num_clients=3):
        """
        Initialize concurrent tester.
        
        Args:
            host: Server host address
            port: Server port number
            num_clients: Number of concurrent clients to run
        """
        self.host = host
        self.port = port
        self.num_clients = num_clients
        self.results = []
        self.results_lock = threading.Lock()
        
    def run_client_test(self, client_id):
        """
        Run a client test in a thread.
        
        Args:
            client_id: Identifier for this client
        """
        print(f"[CONCURRENT] Client {client_id} starting...")
        
        client = WyndrvrClient(self.host, self.port)
        
        if client.connect():
            try:
                # Run latency test only for concurrent testing
                latency_stats = client.test_latency(count=5)
                
                with self.results_lock:
                    self.results.append({
                        'client_id': client_id,
                        'latency': latency_stats
                    })
                    
            finally:
                client.disconnect()
        else:
            print(f"[CONCURRENT] Client {client_id} failed to connect")
            
    def run(self):
        """Run concurrent tests."""
        print(f"\n[CONCURRENT] Starting {self.num_clients} concurrent clients...")
        
        threads = []
        start_time = time.time()
        
        for i in range(self.num_clients):
            thread = threading.Thread(target=self.run_client_test, args=(i+1,))
            thread.start()
            threads.append(thread)
            
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
        end_time = time.time()
        
        # Display results
        print(f"\n[CONCURRENT] All clients completed in {end_time - start_time:.2f} seconds")
        print("\n[CONCURRENT] Results Summary:")
        
        for result in self.results:
            client_id = result['client_id']
            latency = result.get('latency')
            
            if latency:
                print(f"  Client {client_id}: Avg Latency = {latency['avg']:.2f} ms")
            else:
                print(f"  Client {client_id}: Test failed")


def main():
    """Main entry point for the client."""
    parser = argparse.ArgumentParser(
        description='Wyndrvr Client - Network Bandwidth and Latency Testing'
    )
    parser.add_argument(
        '--host',
        default='localhost',
        help='Server host address (default: localhost)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5001,
        help='Server port number (default: 5001)'
    )
    parser.add_argument(
        '--test',
        choices=['latency', 'download', 'upload', 'all'],
        default='all',
        help='Test to run (default: all)'
    )
    parser.add_argument(
        '--count',
        type=int,
        default=10,
        help='Number of latency tests (default: 10)'
    )
    parser.add_argument(
        '--size',
        type=int,
        default=10,
        help='Size for bandwidth tests in MB (default: 10)'
    )
    parser.add_argument(
        '--concurrent',
        type=int,
        metavar='N',
        help='Run N concurrent clients (uses threads)'
    )
    
    args = parser.parse_args()
    
    # Handle concurrent mode
    if args.concurrent:
        tester = ConcurrentTester(args.host, args.port, args.concurrent)
        tester.run()
        return
        
    # Single client mode
    client = WyndrvrClient(host=args.host, port=args.port)
    
    if not client.connect():
        sys.exit(1)
        
    try:
        if args.test == 'all':
            client.run_all_tests(
                latency_count=args.count,
                bandwidth_size_mb=args.size
            )
        elif args.test == 'latency':
            client.test_latency(count=args.count)
        elif args.test == 'download':
            client.test_bandwidth_download(size_mb=args.size)
        elif args.test == 'upload':
            client.test_bandwidth_upload(size_mb=args.size)
            
    except KeyboardInterrupt:
        print("\n[CLIENT] Test interrupted")
    finally:
        client.disconnect()


if __name__ == '__main__':
    main()
