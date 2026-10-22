"""
Latency Test Script for ESP32 Communication
Tests roundtrip latency for commands sent to ESP32
"""

import sys
import os
import time
import statistics
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.esp32_comm import ESP32Communicator

class LatencyTester:
    def __init__(self):
        self.comm = ESP32Communicator()
        self.response_times = []
        self.received_responses = []
        self.response_event = threading.Event()
        
    def response_callback(self, line):
        """Callback for received data"""
        self.received_responses.append(time.perf_counter())
        self.response_event.set()
    
    def connect(self):
        """Connect to ESP32"""
        print(">>> Scanning for ESP32 device...")
        success, msg = self.comm.scan_and_connect()
        if not success:
            print(f"[X] Connection failed: {msg}")
            return False
        print(f"[OK] {msg}")
        
        # Set up callback
        self.comm.set_raw_data_callback(self.response_callback)
        return True
    
    def test_latency(self, num_tests=100):
        """Test roundtrip latency"""
        print(f"\n>>> Running {num_tests} latency tests...")
        print("   (Sending 'help' command repeatedly)\n")
        
        latencies = []
        
        for i in range(num_tests):
            self.response_event.clear()
            self.received_responses.clear()
            
            # Record send time
            start = time.perf_counter()
            self.comm.send_command("help")
            
            # Wait for response (timeout 1s)
            if self.response_event.wait(timeout=1.0):
                end = self.received_responses[0]
                latency_ms = (end - start) * 1000
                latencies.append(latency_ms)
                
                if (i + 1) % 10 == 0:
                    print(f"   Completed {i + 1}/{num_tests} tests...")
            else:
                print(f"   [!] Test {i + 1} timed out")
            
            # Small delay between tests
            time.sleep(0.05)
        
        return latencies
    
    def print_results(self, latencies):
        """Print test results"""
        if not latencies:
            print("\n[X] No successful tests")
            return
        
        avg = statistics.mean(latencies)
        median = statistics.median(latencies)
        min_lat = min(latencies)
        max_lat = max(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0
        
        print("\n" + "="*60)
        print("LATENCY TEST RESULTS")
        print("="*60)
        print(f"   Tests Completed: {len(latencies)}")
        print(f"   Average:         {avg:.2f} ms")
        print(f"   Median:          {median:.2f} ms")
        print(f"   Min:             {min_lat:.2f} ms")
        print(f"   Max:             {max_lat:.2f} ms")
        print(f"   Std Dev:         {stdev:.2f} ms")
        print("="*60)
        
        # Success criteria
        print("\nSUCCESS CRITERIA:")
        if avg < 20:
            print(f"   [OK] Average latency < 20ms: {avg:.2f} ms")
        else:
            print(f"   [X] Average latency >= 20ms: {avg:.2f} ms")
        
        if max_lat < 50:
            print(f"   [OK] Max latency < 50ms: {max_lat:.2f} ms")
        else:
            print(f"   [X] Max latency >= 50ms: {max_lat:.2f} ms")
        print()
    
    def disconnect(self):
        """Disconnect from ESP32"""
        self.comm.disconnect()
        print("Disconnected")

def main():
    tester = LatencyTester()
    
    # Connect
    if not tester.connect():
        return 1
    
    try:
        # Run latency test
        latencies = tester.test_latency(num_tests=100)
        
        # Print results
        tester.print_results(latencies)
        
    except KeyboardInterrupt:
        print("\n\n[!] Test interrupted by user")
    finally:
        tester.disconnect()
    
    return 0

if __name__ == "__main__":
    exit(main())
