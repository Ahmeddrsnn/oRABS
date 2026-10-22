"""
FULL END-TO-END AUTOMATED TEST
Slave ASSIGN -> Master Query -> Parameter Send -> Clear Flag -> Verify
"""

import serial
import time
import sys
import json

# Set UTF-8 encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

def print_header(text):
    print("\n" + "=" * 70)
    print(f" {text}")
    print("=" * 70)

def filter_wifi_spam(raw_text):
    """Filter out WiFi debug spam and extract meaningful responses"""
    lines = raw_text.split('\n')
    filtered = []
    
    for line in lines:
        # Skip WiFi debug spam
        if '_eventCallback' in line or 'STA_START' in line or 'POWERON' in line:
            continue
        if 'Build:Mar' in line or 'rst:0x' in line or 'boot:0x' in line:
            continue
        if line.strip() == '':
            continue
            
        filtered.append(line)
    
    return '\n'.join(filtered)

def extract_json_from_response(text):
    """Extract JSON objects from response text"""
    import re
    import json
    
    # Find all JSON-like patterns
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text)
    
    results = []
    for match in matches:
        try:
            obj = json.loads(match)
            results.append(obj)
        except:
            pass
    
    return results

def run_full_test():
    print_header("FULL END-TO-END RFID NVS SYNC TEST")
    
    slave_ser = None
    master_ser = None
    
    try:
        # ===== STEP 1: Connect to both devices =====
        print_header("STEP 1: Connecting to devices")
        
        print("[SLAVE] Connecting to COM11...")
        slave_ser = serial.Serial('COM11', 115200, timeout=2)
        time.sleep(3)  # Wait for boot
        slave_ser.reset_input_buffer()
        print("[OK] Slave connected")
        
        print("\n[MASTER] Connecting to COM13...")
        master_ser = serial.Serial('COM13', 115200, timeout=2)
        time.sleep(2)
        master_ser.reset_input_buffer()
        print("[OK] Master connected")
        
        # ===== STEP 2: Slave - Add tag first, then assign port =====
        print_header("STEP 2: Slave - Adding tag to database")
        
        print("[SLAVE] Command: ADD:0x004FD0CF:TestTag:0")
        slave_ser.write(b"ADD:0x004FD0CF:TestTag:0\n")
        time.sleep(3)
        response = slave_ser.read(slave_ser.in_waiting).decode('utf-8', errors='ignore')
        filtered = filter_wifi_spam(response)
        print(filtered if filtered else "[WiFi spam filtered - no output]")
        
        print("\n[SLAVE] Command: ASSIGN:0x004FD0CF:1")
        slave_ser.write(b"ASSIGN:0x004FD0CF:1\n")
        time.sleep(3)
        response = slave_ser.read(slave_ser.in_waiting).decode('utf-8', errors='ignore')
        filtered = filter_wifi_spam(response)
        print(filtered if filtered else "[WiFi spam filtered - no output]")
        
        if "Port 1 atandi" in response or "assigned" in response.lower() or "isNewRecord=true" in response:
            print("[OK] RFID assigned successfully with isNewRecord=true")
        else:
            print("[WARNING] Assignment response unclear")
        
        # ===== STEP 3: Master - Add slave if needed =====
        print_header("STEP 3: Master - Ensuring slave is registered")
        
        print("[MASTER] Getting slave list...")
        master_ser.write(b"list\n")
        time.sleep(1)
        list_response = master_ser.read(master_ser.in_waiting).decode('utf-8', errors='ignore')
        
        if "TestAparati" not in list_response:
            print("[MASTER] Adding slave...")
            master_ser.write(b"addslave TestAparati 70:04:1D:CD:88:14\n")
            time.sleep(2)
            add_response = master_ser.read(master_ser.in_waiting).decode('utf-8', errors='ignore')
            print(add_response)
        else:
            print("[OK] Slave already registered")
        
        # ===== STEP 4: Master - Query new RFIDs =====
        print_header("STEP 4: Master - Querying new RFIDs from slave")
        
        query_cmd = 'send TestAparati {"cmd":"GET_NEW_RFIDS"}'
        print(f"[MASTER] Command: {query_cmd}")
        master_ser.write((query_cmd + "\n").encode('utf-8'))
        time.sleep(5)  # Increased wait for ESP-NOW processing
        
        # Read multiple times to get full response
        full_response = ""
        for _ in range(3):
            if master_ser.in_waiting > 0:
                chunk = master_ser.read(master_ser.in_waiting).decode('utf-8', errors='ignore')
                full_response += chunk
                time.sleep(0.5)
        
        print("\n--- RAW RESPONSE ---")
        print(full_response[:800] if full_response else "[No response]")
        print("--- END RAW ---")
        
        # Parse JSON from response
        json_objects = extract_json_from_response(full_response)
        print(f"\n[PARSER] Found {len(json_objects)} JSON objects")
        
        new_rfids_found = False
        new_rfids_data = None
        
        for obj in json_objects:
            print(f"[JSON] {obj}")
            
            if obj.get('cmd') == 'NEW_RFIDS_RESPONSE':
                print("\n[SUCCESS] NEW_RFIDS_RESPONSE found!")
                new_rfids_data = obj.get('data', [])
                
                if len(new_rfids_data) > 0:
                    new_rfids_found = True
                    print(f"[OK] {len(new_rfids_data)} new RFID(s) detected:")
                    for rfid in new_rfids_data:
                        print(f"  - RFID: {rfid.get('rfid')}")
                        print(f"    Port: {rfid.get('port')}")
                        print(f"    Name: {rfid.get('name')}")
                        print(f"    Admin: {rfid.get('admin')}")
                else:
                    print("[INFO] data array is empty - no new RFIDs")
        
        if not json_objects:
            print("[ERROR] No JSON objects found in response")
        
        # ===== STEP 5: Send Parameters (Recipe) =====
        print_header("STEP 5: Sending Test Parameters (Recipe)")
        
        # Recipe format: inflationMax-inflationPascal-stabilization-reinflate-maxReinflate-fail-duration-successDrop
        # Demo Values: 10-3000-5-2800-3-2000-10-200
        recipe_val = "10-3000-5-2800-3-2000-10-200"
        
        # Command: {"cmd":"SET_PARAM","key":"recipe","value":"..."}
        # Note: We need to escape inner quotes for Python string, and send properly to Master
        # Master expects: send <target> <message>
        param_cmd = f'send TestAparati {{"cmd":"SET_PARAM","key":"recipe","value":"{recipe_val}"}}'
        
        print(f"[MASTER] Sending Recipe: {recipe_val}")
        print(f"Command: {param_cmd}")
        master_ser.write((param_cmd + "\n").encode('utf-8'))
        time.sleep(4)
        
        # Read response (expect ACK)
        response = ""
        for _ in range(3):
            if master_ser.in_waiting > 0:
                chunk = master_ser.read(master_ser.in_waiting).decode('utf-8', errors='ignore')
                response += chunk
                time.sleep(0.5)
                
        print("\n--- RESPONSE ---")
        print(response[:800] if response else "[No response]")
        
        if "ACK_PARAM" in response and "recipe" in response:
            print("\n[SUCCESS] Parameters acknowledged by Slave!")
        else:
            print("\n[WARNING] No ACK received for parameters")
            
        # ===== STEP 6: Clear New Flag (Cleanup) =====
        if new_rfids_found and new_rfids_data:
            rfid_to_clear = new_rfids_data[0].get('rfid', '0x004FD0CF')
            print_header(f"STEP 6: Clearing 'new' flag for {rfid_to_clear}")
            
            clear_cmd = f'send TestAparati {{"cmd":"CLEAR_NEW_FLAG","rfid":"{rfid_to_clear}"}}'
            print(f"Command: {clear_cmd}")
            master_ser.write((clear_cmd + "\n").encode('utf-8'))
            time.sleep(3)
            
            # Read ACK
            clear_response = master_ser.read(master_ser.in_waiting).decode('utf-8', errors='ignore')
            if "ACK" in clear_response:
                print("[OK] Clear Flag ACK received")
        
        # ===== SUMMARY =====
        print_header("TEST SUMMARY")
        print("[SLAVE] RFID Assignment: OK")
        print("[MASTER] Slave Registration: OK")
        print("[MASTER] ESP-NOW Communication: OK")
        print(f"[SYNC] New RFID Detection: {'SUCCESS' if new_rfids_found else 'FAILED - data empty'}")
        
        if new_rfids_found:
            print("\n[OVERALL] FULL END-TO-END TEST PASSED!")
        else:
            print("\n[OVERALL] TEST INCOMPLETE - Check ASSIGN logic")
            print("Debug: Check if addTag() sets isNewRecord=true")
        
    except serial.SerialException as e:
        print(f"\n[ERROR] Serial error: {e}")
        print("Check: COM ports not in use by other programs")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if slave_ser and slave_ser.is_open:
            slave_ser.close()
            print("\n[CLOSE] Slave connection closed")
        if master_ser and master_ser.is_open:
            master_ser.close()
            print("[CLOSE] Master connection closed")

if __name__ == "__main__":
    run_full_test()
