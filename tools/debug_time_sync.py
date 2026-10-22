import serial
import time
import serial.tools.list_ports
from datetime import datetime
import json

def list_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def find_master_and_slaves():
    ports = list_ports()
    print(f"Available ports: {ports}")
    
    for port in ports:
        try:
            print(f"Checking {port}...")
            ser = serial.Serial(port, 115200, timeout=1)
            ser.dtr = True
            ser.rts = True
            time.sleep(2) # Wait for reset
            
            # Send HELP/LIST command
            ser.write(b'list\n')
            time.sleep(1)
            
            response = ser.read_all().decode('utf-8', errors='ignore')
            print(f"Response from {port}: {response[:200]}...")
            
            if "SLAVE LIST" in response or "Commands" in response:
                print(f"✅ Found Master on {port}")
                
                # Extract slaves
                slaves = []
                lines = response.split('\n')
                parsing = False
                for line in lines:
                    if "--- SLAVE LIST ---" in line:
                        parsing = True
                        continue
                    if "------------------" in line:
                        parsing = False
                        break
                    if parsing and "[" in line:
                        # Extract name
                        try:
                            parts = line.split('|')
                            if len(parts) > 0:
                                name_part = line.split(']')[1].strip().split('(')[0].strip()
                                slaves.append(name_part)
                        except:
                            pass
                
                return ser, slaves, port
            
            ser.close()
        except Exception as e:
            print(f"Error checking {port}: {e}")
            
    return None, [], None

def send_time_sync(ser, slave_name):
    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    json_payload = json.dumps({"cmd": "SET_TIME", "datetime": time_str})
    full_cmd = f"send {slave_name} {json_payload}\n"
    
    print(f"Sending to {slave_name}: {full_cmd.strip()}")
    ser.write(full_cmd.encode('utf-8'))
    
    # Wait for response
    print("Waiting for response...")
    start = time.time()
    response_buffer = ""
    while time.time() - start < 5:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            print(data, end='')
            response_buffer += data
        time.sleep(0.1)

    if "ACK_SET_TIME" in response_buffer:
        print(f"\n✅ SUCCESS: Time set on {slave_name}")
        return True
    else:
        print(f"\n❌ FAILURE: No ACK received from {slave_name}")
        return False

def main():
    print("--- Time Sync Debugger ---")
    ser, slaves, port = find_master_and_slaves()
    
    if not ser:
        print("❌ Could not find Master device.")
        return

    if not slaves:
        print("❌ Master found but NO slaves listed. Check ESP-NOW connection.")
        ser.close()
        return

    print(f"Found Slaves: {slaves}")
    
    for slave in slaves:
        send_time_sync(ser, slave)
        time.sleep(1)
        
    ser.close()

if __name__ == "__main__":
    main()
