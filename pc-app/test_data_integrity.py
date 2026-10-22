"""
Data Integrity Test Script for ESP32 Communication
Tests that all data sent is received without loss or corruption
"""

import sys
import os
import time
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.esp32_comm import ESP32Communicator

class DataIntegrityTester:
    def __init__(self):
        self.comm = ESP32Communicator()
        self.received_lines = []
        self.lock = threading.Lock()
        
    def data_callback(self, line):
        """Callback for received data"""
        with self.lock:
            self.received_lines.append(line)
    
    def connect(self):
        """Connect to ESP32"""
        print(">>> Scanning for ESP32 device...")
        success, msg = self.comm.scan_and_connect()
        if not success:
            print(f"[X] Connection failed: {msg}")
            return False
        print(f"[OK] {msg}")
        
        # Set up callback
        self.comm.set_raw_data_callback(self.data_callback)
        return True
    
    def test_data_integrity(self, num_messages=100):
        """Test data integrity by sending multiple commands"""
        print(f"\n>>> Testing data integrity with {num_messages} messages...")
        print("   (Sending rapid 'help' commands)\n")
        
        # Clear received buffer
        with self.lock:
            self.received_lines.clear()
        
        # Record start count
        start_time = time.time()
        
        # Send multiple commands rapidly
        for i in range(num_messages):
            self.comm.send_command("help")
            if (i + 1) % 10 == 0:
                print(f"   Sent {i + 1}/{num_messages} commands...")
                time.sleep(0.01)  # Small delay to prevent overwhelming
        
        # Wait for responses
        print("\n   [~] Waiting for all responses...")
        time.sleep(3)  # Give time for all responses
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Count responses
        with self.lock:
            total_received = len(self.received_lines)
            # Count actual help responses (contains "Commands" or similar)
            actual_responses = sum(1 for line in self.received_lines 
                                  if any(keyword in line for keyword in 
                                        ["Commands", "HELP", "STATUS", "SLAVE LIST"]))
        
        return {
            'sent': num_messages,
            'total_lines': total_received,
            'actual_responses': actual_responses,
            'duration': duration,
            'throughput': total_received / duration if duration > 0 else 0
        }
    
    def print_results(self, results):
        """Print test results"""
        print("\n" + "="*60)
        print("DATA INTEGRITY TEST RESULTS")
        print("="*60)
        print(f"   Commands Sent:      {results['sent']}")
        print(f"   Total Lines Recv:   {results['total_lines']}")
        print(f"   Actual Responses:   {results['actual_responses']}")
        print(f"   Duration:           {results['duration']:.2f} s")
        print(f"   Throughput:         {results['throughput']:.1f} lines/sec")
        print("="*60)
        
        # Success criteria
        print("\nSUCCESS CRITERIA:")
        
        # Allow some margin for extra log messages
        if results['actual_responses'] >= results['sent'] * 0.95:
            print(f"   [OK] Response rate >= 95%: " +
                  f"{results['actual_responses']}/{results['sent']} " +
                  f"({results['actual_responses']/results['sent']*100:.1f}%)")
        else:
            print(f"   [X] Response rate < 95%: " +
                  f"{results['actual_responses']}/{results['sent']} " +
                  f"({results['actual_responses']/results['sent']*100:.1f}%)")
        
        if results['throughput'] > 100:
            print(f"   [OK] Throughput > 100 lines/sec: {results['throughput']:.1f}")
        else:
            print(f"   [!] Throughput <= 100 lines/sec: {results['throughput']:.1f}")
        print()
    
    def disconnect(self):
        """Disconnect from ESP32"""
        self.comm.disconnect()
        print("Disconnected")

def main():
    tester = DataIntegrityTester()
    
    # Connect
    if not tester.connect():
        return 1
    
    try:
        # Run integrity test
        results = tester.test_data_integrity(num_messages=100)
        
        # Print results
        tester.print_results(results)
        
    except KeyboardInterrupt:
        print("\n\n[!] Test interrupted by user")
    finally:
        tester.disconnect()
    
    return 0

if __name__ == "__main__":
    exit(main())
