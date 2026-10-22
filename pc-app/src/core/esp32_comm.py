"""
ESP32 Communication Module - ESP-NOW Master
Handles serial communication with ESP-NOW Master device
"""

import serial
import serial.tools.list_ports
import time
import threading
import queue
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
import re
import json
from utils.app_logger import get_logger

_logger = get_logger("esp32_comm")


class ESP32Communicator:
    """Manages serial communication with ESP-NOW Master device"""
    
    def __init__(self, baud_rate: int = 115200, timeout: float = 0.01):
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.serial_port: Optional[serial.Serial] = None
        self.port_name: Optional[str] = None
        self.is_connected = False
        self.auto_reconnect = True
        self.read_thread: Optional[threading.Thread] = None
        self.process_thread: Optional[threading.Thread] = None
        self.rx_queue = queue.Queue()
        self.running = False
        self.parsing_slaves = False
        self.current_slaves_buffer = []
        self.data_callback: Optional[Callable] = None
        self.status_callback: Optional[Callable] = None
        self.slave_list_callback: Optional[Callable] = None
        self.raw_data_callback: Optional[Callable] = None
        self.sent_data_callback: Optional[Callable] = None
        self.slave_devices = []  # List of connected slave devices
        self.crc_callback: Optional[Callable] = None
        self.new_rfid_callback: Optional[Callable] = None
        self.battery_cache: Dict[str, int] = {}  # Pre-login battery data cache
        self.device_id_cache: Dict[str, str] = {}  # device_name -> device_id (from HELLO "did")
        self._write_lock = threading.Lock()  # Serial write thread safety

    def set_raw_data_callback(self, callback: Callable):
        """Set callback for raw data lines (RX)"""
        self.raw_data_callback = callback

    def set_sent_data_callback(self, callback: Callable):
        """Set callback for sent data lines (TX)"""
        self.sent_data_callback = callback

    # ... (existing methods remain unchanged until _read_loop) ...

    def set_slave_list_callback(self, callback: Callable):
        """Set callback for slave list updates"""
        self.slave_list_callback = callback

    def set_crc_callback(self, callback: Callable):
        """Set callback for CRC reports"""
        self.crc_callback = callback

    def set_new_rfid_callback(self, callback: Callable):
        """Set callback for NEW_RFID_ITEM events"""
        self.new_rfid_callback = callback

    def clear_callbacks(self):
        """Clear all callbacks (call before destroying UI panels to prevent dangling refs)"""
        self.data_callback = None
        self.status_callback = None
        self.slave_list_callback = None
        self.raw_data_callback = None
        self.sent_data_callback = None
        self.crc_callback = None
        self.new_rfid_callback = None

    def _read_loop(self):
        """Producer Thread: Reads raw bytes from serial and pushes lines to queue"""
        buffer = b""  # Binary buffer — decode only after finding \n to prevent UTF-8 split
        READ_BUFFER_SIZE = 4096  # Increased buffer for high speed
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10  # Bu kadar ardışık hata → port öldü, yeniden aç
        
        while self.running and self.is_connected:
            try:
                if self.serial_port and self.serial_port.in_waiting > 0:
                    try:
                        bytes_to_read = min(self.serial_port.in_waiting, READ_BUFFER_SIZE)
                        received = self.serial_port.read(bytes_to_read)
                        buffer += received
                        consecutive_errors = 0  # Başarılı okuma → hata sayacı sıfırla
                    except (serial.SerialException, PermissionError, OSError) as e:
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            _logger.error("Port ölü (%d hata), yeniden bağlanılıyor...", consecutive_errors)
                            self._reopen_port()
                            consecutive_errors = 0
                            buffer = b""
                        else:
                            time.sleep(0.1)
                        continue
                    except Exception as e:
                        _logger.debug("Read decode error: %s", e)
                        continue
                    
                    while b"\n" in buffer:
                        raw_line, buffer = buffer.split(b"\n", 1)
                        line = raw_line.decode('utf-8', errors='replace').strip()
                        if line:
                            self.rx_queue.put(line)  # Push to queue immediately
                else:
                    time.sleep(0.001)
            except (serial.SerialException, PermissionError, OSError):
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    _logger.error("Port ölü (%d hata), yeniden bağlanılıyor...", consecutive_errors)
                    self._reopen_port()
                    consecutive_errors = 0
                    buffer = ""
                time.sleep(0.2)
            except Exception as e:
                _logger.warning("Read loop unexpected error: %s", e)
                time.sleep(0.5)
    
    def _reopen_port(self):
        """USB re-enumeration sonrası portu yeniden aç (read thread içinden)"""
        port = self.port_name
        if not port:
            return
        try:
            if self.serial_port:
                try:
                    self.serial_port.close()
                except Exception:
                    pass
            self.serial_port = None
            
            # Master'ın USB'yi yeniden enumerate etmesini bekle (3×1s = max 3s)
            for attempt in range(3):
                time.sleep(1)
                try:
                    self.serial_port = serial.Serial(
                        port=port,
                        baudrate=self.baud_rate,
                        timeout=self.timeout,
                        write_timeout=None,
                        dsrdtr=False,   # DTR dokunma → ESP32-S3 reset ENGELLE
                        rtscts=False
                    )
                    _ = self.serial_port.in_waiting  # Port test
                    print(f"[ESP32-COMM] Port {port} yeniden açıldı (deneme {attempt+1})")
                    _logger.info("Port %s yeniden açıldı (deneme %d)", port, attempt+1)
                    return
                except Exception:
                    _logger.debug("Port %s reopen attempt %d failed", port, attempt+1)
                    if self.serial_port:
                        try:
                            self.serial_port.close()
                        except Exception:
                            pass
                        self.serial_port = None
                    continue
            
            print(f"[ESP32-COMM] Port {port} yeniden açılamadı!")
            _logger.error("Port %s yeniden açılamadı!", port)
            self.is_connected = False
        except Exception as e:
            _logger.error("Reopen hatası: %s", e)
            self.is_connected = False

    def _processing_loop(self):
        """Consumer Thread: Processes lines from queue (Parsing & Callbacks)"""
        while self.running:
            try:
                # Bloklayıcı get (timeout ile güvenli çıkış için)
                line = self.rx_queue.get(timeout=0.1)
                self._process_line(line)
                self.rx_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                _logger.error("Processing error: %s", e)

    def _process_line(self, line: str):
        """Parse a single line from serial"""
        try:
            self._process_line_inner(line)
        except (RuntimeError, ReferenceError):
            # Qt C++ object deleted — clear all callbacks to prevent further crashes
            _logger.warning("Qt object deleted, clearing callbacks")
            self.clear_callbacks()
        except Exception as e:
            # Processing thread ölmesin — her türlü hatayı yakala ve devam et
            _logger.error("Processing error (non-fatal): %s", e)

    def _process_line_inner(self, line: str):
        """Internal line processing (separated for exception safety)"""
        if self.raw_data_callback:
            self.raw_data_callback(line)

        # Check for start of slave list
        if "--- SLAVE LIST ---" in line:
            self.parsing_slaves = True
            self.current_slaves_buffer = []
            return
        
        # Check for end of slave list
        if self.parsing_slaves and "------------------" in line:
            self.parsing_slaves = False
            self.slave_devices = self.current_slaves_buffer
            if self.slave_list_callback:
                self.slave_list_callback(self.current_slaves_buffer)
            
            return
        
        # Parse slave line
        if self.parsing_slaves:
            match = re.match(r'\[(\d+)\]\s+(\S+)\s+\(([^)]+)\)\s+\|\s+(.+)', line)
            if match:
                self.current_slaves_buffer.append({
                    'id': match.group(1),
                    'name': match.group(2),
                    'mac': match.group(3),
                    'status': match.group(4)
                })
        
        # Try to parse JSON data
        try:
            json_str = line
            match = re.search(r"\[(.*?)\]\s*(\{.*\})", line)
            if match:
                json_str = match.group(2)
                
            data = json.loads(json_str)
            if not isinstance(data, dict):
                return  # json.loads düz string/sayı döndü — dict değil, atla
            if self.data_callback and data.get('type') == 'data':
                self.data_callback(data)
            elif self.status_callback and data.get('type') == 'status':
                self.status_callback(data)
            
            cmd = data.get('cmd')
            # Cache battery data regardless of whether handlers are registered
            if cmd == 'STATUS_REPLY':
                dev_name = data.get('device', '')
                bat = data.get('battery')
                if dev_name and bat is not None:
                    self.battery_cache[dev_name] = int(bat)

            if cmd == 'CRC_REPORT':
                if self.crc_callback:
                    self.crc_callback(data)
            elif cmd == 'RFID_ITEM' or cmd == 'RFID_DETECTED':
                print(f"DEBUG: RFID Event received: {cmd} -> {data}")
                if self.new_rfid_callback:
                    self.new_rfid_callback(data)
        except json.JSONDecodeError:
            # Stream satırları (@S: prefix ile gelir) log'a yazılmasın
            if '@S:' not in line:
                _logger.debug("Non-JSON line: %.80s", line)
    
    def list_available_ports(self):
        """List ESP32-S3 ports including HWCDC (USB-Serial-JTAG) which pyserial can't enumerate.
        Uses pyserial enumeration + WMI fallback for HWCDC ports."""
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        seen_devices = {p.device for p in ports}
        
        # WMI fallback: HWCDC ports ("USB Seri Cihaz") not visible to pyserial
        try:
            import subprocess
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-WmiObject Win32_SerialPort | Select-Object DeviceID,Name | ConvertTo-Json'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0 and result.stdout.strip():
                import json as _json
                wmi_ports = _json.loads(result.stdout)
                if isinstance(wmi_ports, dict):
                    wmi_ports = [wmi_ports]
                for wp in wmi_ports:
                    dev = wp.get('DeviceID', '')
                    name = wp.get('Name', '')
                    if dev and dev not in seen_devices:
                        # Create a minimal port info object
                        class WmiPort:
                            def __init__(self, device, description):
                                self.device = device
                                self.description = description
                                self.hwid = ''
                                self.vid = 0x303A if 'USB Seri' in description else 0
                                self.pid = 0x1001 if 'USB Seri' in description else 0
                        ports.append(WmiPort(dev, name))
                        seen_devices.add(dev)
        except Exception:
            _logger.debug("WMI port query failed")
            pass
        
        # Filter: ESP32-S3 USB (VID:PID match) or USB Seri Cihaz (HWCDC)
        valid_ports = []
        for p in ports:
            is_esp32 = getattr(p, 'vid', 0) == 0x303A and getattr(p, 'pid', 0) == 0x1001
            is_hwcdc = 'USB Seri' in getattr(p, 'description', '')
            if is_esp32 or is_hwcdc:
                valid_ports.append(p)
        return valid_ports
    
    def connect(self, port: str = None, **kwargs) -> tuple[bool, str]:
        """
        Connect to ESP32 device
        :param port: COM port name
        """
        try:
            if port is None:
                # Legacy auto-detect
                ports = self.list_available_ports()
                if not ports:
                    return False, "No COM ports available"
                port = ports[0].device
            
            # Close existing if open
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()

            # ═══════════════════════════════════════════════════════════
            # ESP32-S3 HWCDC (USB-Serial-JTAG) ilk açılışta kısa bir USB
            # re-enumeration yapabilir. Bu durumda port handle geçersiz olur.
            # Çözüm: Aç → test oku → hata varsa kapat/bekle/tekrar aç.
            # ═══════════════════════════════════════════════════════════
            MAX_OPEN_RETRIES = 3
            for attempt in range(MAX_OPEN_RETRIES):
                try:
                    if self.serial_port and self.serial_port.is_open:
                        self.serial_port.close()
                    
                    self.serial_port = serial.Serial(
                        port=port,
                        baudrate=self.baud_rate,
                        timeout=0.5,  # Yeterli timeout ile açılış testi
                        write_timeout=None,
                        dsrdtr=False,   # DTR dokunma → ESP32-S3 HWCDC reset ENGELLE
                        rtscts=False
                    )
                    
                    # Kısa test: port gerçekten okunabiliyor mu?
                    time.sleep(0.3)
                    try:
                        _ = self.serial_port.in_waiting
                        # Birkaç satır okumayı dene (boot mesajları gelebilir)
                        for _ in range(5):
                            self.serial_port.readline()
                        break  # Port sağlam, döngüden çık
                    except (serial.SerialException, PermissionError, OSError):
                        # USB re-enumeration — port handle geçersiz
                        _logger.warning("Port %s USB re-enum (deneme %d/%d)", port, attempt+1, MAX_OPEN_RETRIES)
                        try:
                            self.serial_port.close()
                        except Exception:
                            pass
                        self.serial_port = None
                        # Master boot süresi: ~2-3 saniye
                        time.sleep(4 if attempt == 0 else 2)
                        continue
                except serial.SerialException:
                    if attempt < MAX_OPEN_RETRIES - 1:
                        time.sleep(3)
                        continue
                    raise
            
            if not self.serial_port or not self.serial_port.is_open:
                return False, f"Port {port} açılamadı ({MAX_OPEN_RETRIES} deneme)"
            
            # Timeout'u normal değere geri al (okuma thread'i için)
            self.serial_port.timeout = self.timeout
            
            self.port_name = port

            self.is_connected = True
            
            # Start threads
            self.running = True
            
            # 1. Processing Thread (Consumer)
            self.process_thread = threading.Thread(target=self._processing_loop, daemon=True)
            self.process_thread.start()
            
            # 2. Read Thread (Producer)
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()
            
            return True, f"Connected to {port}"
        
        except serial.SerialException as e:
            self.is_connected = False
            if "PermissionError" in str(e) or "Access is denied" in str(e):
                return False, f"Port {port} is busy or access denied."
            return False, f"Connection failed to {port}: {e}"
        except Exception as e:
            self.is_connected = False
            return False, f"Unexpected error: {str(e)}"

    def scan_and_connect(self) -> tuple[bool, str]:
        """Scan all ports and connect to the first valid ESP-NOW Master"""
        ports = self.list_available_ports()
        if not ports:
            return False, "No COM ports found."
        
        # Helper to score ports
        def score_port(port_info):
            desc = port_info.description.upper()
            hwid = (port_info.hwid or "").upper()
            # Highest Priority: Espressif ESP32-S3 Native USB CDC (VID=303A, PID=1001)
            # Windows doesn't expose USB product string via description, so match VID:PID
            if "VID:PID=303A:1001" in hwid: return 200
            # High Priority: Our custom Master label (legacy / fallback)
            if "ESP-NOW MASTER" in desc: return 100
            # High Priority: Silicon Labs CP210x (standard ESP32-S3 Bridge)
            if "CP210" in desc: return 80
            # Medium: Generic USB-Serial but not Bluetooth
            if "USB" in desc and "BLUETOOTH" not in desc: return 50
            return 0

        # Sort ports by probability
        ports.sort(key=score_port, reverse=True)
        
        for port_info in ports:
            port = port_info.device
            desc = port_info.description
            
            # Skip very unlikely ports (like Bluetooth) to save time
            if score_port(port_info) < 20:
                print(f"Skipping unlikely port: {port} ({desc})")
                continue

            print(f"Scanning {port} ({desc})...")
            success, msg = self.connect(port, test_mode=True)
            if success:
                return True, msg
            
        return False, "No valid ESP-NOW Master device found in available ports."
    
    def disconnect(self):
        """Disconnect from ESP32 device"""
        self.running = False
        
        # 1. Read thread'i kapat
        if self.read_thread:
            self.read_thread.join(timeout=2)
            self.read_thread = None
        
        # 2. Process thread'i kapat (Thread Leak Fix)
        if self.process_thread:
            self.process_thread.join(timeout=2)
            self.process_thread = None
        
        # 3. Kuyruktaki stale veriyi temizle
        while not self.rx_queue.empty():
            try:
                self.rx_queue.get_nowait()
            except queue.Empty:
                break
        
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        
        self.is_connected = False
        self.port_name = None
    
    def send_command(self, command: str) -> str:
        """
        Send text command to ESP-NOW Master and get response.
        Thread-safe: _write_lock prevents interleaved writes from
        processing thread (HELLO handler) and UI thread (QTimer).
        """
        if not self.is_connected or not self.serial_port:
            return ""
        
        try:
            # NOT: reset_input_buffer() KALDIRILDI!
            # read_loop thread çalışırken reset_input_buffer() çağırmak
            # OS seri port tamponu temizler — stream, THP chunk, JSON yanıt kaybına neden olur.
            
            # Thread-safe write
            with self._write_lock:
                self.serial_port.write((command + '\n').encode('utf-8'))
            
            # Notify callback (TX)
            if self.sent_data_callback:
                self.sent_data_callback(command)
            
            # If read loop is running, do not try to read response here as it causes race condition
            # and blocks the main thread.
            if self.read_thread and self.read_thread.is_alive():
                return "Command Sent (Async)"

            # Only read if no background thread is handling reading
            time.sleep(0.5)
            
            # Read response
            response = ""
            start_time = time.time()
            while time.time() - start_time < 3:  # 3 second timeout
                if self.serial_port.in_waiting > 0:
                    chunk = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='ignore')
                    response += chunk
                    time.sleep(0.1)
                else:
                    if response:
                        break
                    time.sleep(0.1)
            
            return response.strip()
        
        except Exception as e:
            _logger.error("Error sending command: %s", e)
            return ""
    
    def get_slave_list(self) -> None:
        """
        Request slave list update.
        Response will be handled by _read_loop and slave_list_callback.
        """
        self.send_command("list")
        # No return value, data comes via callback
    
    def set_parameter(self, target: str, key: str, value: str) -> str:
        """
        Set parameter on target device
        setparam <TARGET> <KEY> <VALUE>
        """
        cmd = f"setparam {target} {key} {value}"
        return self.send_command(cmd)
    
    def set_recipe(self, target: str, recipe: str) -> str:
        """
        Set recipe on target device
        setparam <TARGET> recipe <P1-P2-P3...>
        """
        cmd = f"setparam {target} recipe {recipe}"
        return self.send_command(cmd)
    
    def query_new_rfids(self, target_device: str) -> str:
        """
        Query slave for all RFID records.
        Sends GET_ALL_RFIDS command to specified slave device.
        (GET_NEW_RFIDS does not exist on ESP side — fixed Bug #2)
        """
        command = f'send {target_device} {{"cmd":"GET_ALL_RFIDS"}}'
        return self.send_command(command)
    
    def set_name(self, target: str, new_name: str) -> str:
        """
        Change device name
        setname <TARGET> <NEW NAME>
        """
        cmd = f"setname {target} {new_name}"
        return self.send_command(cmd)
    

    
    def set_data_callback(self, callback: Callable):
        """Set callback for real-time data updates"""
        self.data_callback = callback
    
    def set_status_callback(self, callback: Callable):
        """Set callback for status updates"""
        self.status_callback = callback


# Example ESP32 response formats:
# 
# Status response:
# {"type": "status", "status": "IDLE", "timestamp": "2024-01-01T12:00:00"}
#
# Data response:
# {"type": "data", "pressure": 50.5, "temperature": 25.3, "leak_detected": false, "timestamp": "..."}
#
    def check_device_config(self, target: str) -> str:
        """
        Check device configuration CRC (Sync Check).
        Sends GET_CRC. Response handled in _read_loop -> callback.
        """
        cmd = f"send {target} {{\"cmd\":\"GET_CRC\"}}"
        return self.send_command(cmd)

    def push_device_config(self, target: str, params: Dict[str, Any]):
        """
        Push settings to device (Config Sync).
        """
        # Push all p1-p8 parameters (7 fields: p1-p2-p3-p4-p6-p7-p8)
        recipe_str = f"{params.get('p1',10)}-{params.get('p2',3000)}-{params.get('p3',5)}-{params.get('p4',2800)}-"\
                     f"{params.get('p6',150)}-{params.get('p7',30)}-{params.get('p8',200)}"
        
        self.set_parameter(target, "recipe", recipe_str)
        
        # Push Calibration
        self.set_parameter(target, "PRESSURE_OFFSET", str(params.get('c1', 0.0)))
        self.set_parameter(target, "PRESSURE_MULT", str(params.get('c2', 100.0)))
        self.set_parameter(target, "SEAL_OFFSET", str(params.get('c3', 0.0)))
        self.set_parameter(target, "SEAL_MULT", str(params.get('c4', 100.0)))
        
        # Request new CRC to verify
        # Timer to allow processing
        threading.Timer(2.0, self.check_device_config, args=[target]).start()

    def request_full_rfid_sync(self, target: str) -> str:
        """D7: Delegate to query_new_rfids (identical logic)."""
        return self.query_new_rfids(target)


    def send_time_to_device(self, target: str) -> None:
        """
        Send current time to a specific device.
        target can be MAC address or device name.
        """
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        json_str = json.dumps({"cmd": "SET_TIME", "datetime": time_str})
        
        cmd_slave = f"send {target} {json_str}"
        self.send_command(cmd_slave)
        print(f"Time Sync: Sent to {target}")


