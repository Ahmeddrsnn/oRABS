import re

class MockDB:
    def get_all_ports(self):
        # PC: Port 1 -> Tag A (Correct), Port 2 -> Tag B
        return [
            {'name': 'Port 01', 'rfid_tag': 'TAG_A_CORRECT', 'recipe_id': 1},
            {'name': 'Port 02', 'rfid_tag': 'TAG_B_CORRECT', 'recipe_id': 1}
        ]

class MockESP32:
    def send_command(self, cmd):
        print(f"TX > {cmd}")

class SyncTester:
    def __init__(self):
        self.db = MockDB()
        self.esp32 = MockESP32()
        self.slave_sync_buffers = {}
        
    def log(self, msg, color="black"):
        print(f"[{color.upper()}] {msg}")
        
    def _push_config_to_slave(self, sender, rfid, port, recipe):
        print(f"TX > [SET_TAG_CONFIG] {sender} | RFID:{rfid} Port:{port}")

    def _process_slave_sync(self, sender_name):
        """Execute Strict Sync Logic for a slave (Batch Processed) - COPIED LOGIC + Verification"""
        if sender_name not in self.slave_sync_buffers: return
        
        slave_items = self.slave_sync_buffers.get(sender_name, [])
        self.log(f"Sync Verisi İşleniyor: {sender_name} ({len(slave_items)} kayıt)", color="blue")
        
        all_db_ports = self.db.get_all_ports()
        slave_map = {item['rfid'].upper(): item for item in slave_items}
        db_map = {p['rfid_tag'].upper(): p for p in all_db_ports if p.get('rfid_tag')}
        
        action_taken = False
        
        # A. Check for Orphans in Slave
        for slave_rfid, slave_item in slave_map.items():
            if slave_rfid not in db_map:
                self.log(f"Fazlalık Tespit Edildi: {slave_rfid} (Siliniyor...)", "red")
                del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{slave_rfid}"}}'
                self.esp32.send_command(f"send {sender_name} {del_cmd}")
                action_taken = True
                
        # B. Check for Mismatches
        for slave_rfid, slave_item in slave_map.items():
            if slave_rfid in db_map:
                db_port = db_map[slave_rfid]
                p_match = re.search(r'\d+', db_port.get('name', ''))
                db_port_num = int(p_match.group()) if p_match else 0
                slave_port_num = slave_item.get('port', 0)
                
                if db_port_num != slave_port_num and db_port_num != 0:
                    self.log(f"Port Uyuşmazlığı: {slave_rfid} (PC:{db_port_num} != Slave:{slave_port_num}) -> Düzeltiliyor", "orange")
                    self._push_config_to_slave(sender_name, slave_rfid, db_port_num, db_port.get('recipe_id'))
                    action_taken = True

        # C. Check for duplicate ports
        port_counts = {}
        for item in slave_items:
            p = item.get('port', 0)
            if p > 0:
                if p not in port_counts: port_counts[p] = []
                port_counts[p].append(item)
                
        for p, items_on_port in port_counts.items():
            if len(items_on_port) > 1:
                self.log(f"Çakışma: Port {p} üzerinde {len(items_on_port)} tag var! Temizleniyor...", "red")
                
                for item in items_on_port:
                    conflict_rfid = item.get('rfid')
                    del_cmd = f'{{"cmd":"DELETE_TAG", "rfid":"{conflict_rfid}"}}'
                    self.esp32.send_command(f"send {sender_name} {del_cmd}")
                    if conflict_rfid in slave_map:
                        del slave_map[conflict_rfid]
                    action_taken = True

                target_name = f"Port {p:02d}"
                correct_db = None
                for db_p in all_db_ports:
                    if db_p.get('name') == target_name: 
                        correct_db = db_p
                        break
                
                if correct_db:
                    self.log(f"Çakışma çözümü için doğru tag geri yüklenecek: {correct_db.get('rfid_tag')}", "blue")

        # D. MISSING TAGS (Restore)
        count_restored = 0
        for db_rfid, db_item in db_map.items():
            if db_rfid not in slave_map:
                p_match = re.search(r'\d+', db_item.get('name', ''))
                db_port_num = int(p_match.group()) if p_match else 0
                    
                if db_port_num > 0:
                    self.log(f"Eksik Veri Yükleniyor: {db_rfid} -> Port {db_port_num}", "blue")
                    self._push_config_to_slave(sender_name, db_rfid, db_port_num, db_item.get('recipe_id'))
                    count_restored += 1
        
        if count_restored > 0:
            self.log(f"Geri Yükleme Tamamlandı: {count_restored} adet kayıt gönderildi.", "green")
            action_taken = True
            
        # VERIFICATION STEP (Mocking QTimer)
        if action_taken:
            self.log(f"İşlem yapıldı. Doğrulama için tekrar sorgulanıyor... ({sender_name})", color="#8B5CF6")
            print(f"TIMER SCHEDULED: send {sender_name} {{\"cmd\":\"GET_ALL_RFIDS\"}} (800ms)")
        else:
            self.log(f"Senkronizasyon Tamamlandı: Fark bulunamadı. ({sender_name})", color="green")

def run_test():
    tester = SyncTester()
    sender = "TestDevice"
    
    # SENARYO:
    # Port 1: Duplicate (TAG_A_CORRECT ve TAG_X_WRONG)
    # Port 2: Eksik (TAG_B_CORRECT cihazda yok)
    # Port 5: Fazlalık (TAG_ORPHAN cihazda var ama PC'de yok)
    
    items = [
        {'rfid': 'TAG_A_CORRECT', 'port': 1, 'name': 'Admin'},
        {'rfid': 'TAG_X_WRONG', 'port': 1, 'name': 'OldEmployee'}, # Duplicate Port 1
        {'rfid': 'TAG_ORPHAN', 'port': 5, 'name': 'Unknown'} # Orphan
    ]
    
    tester.slave_sync_buffers[sender] = items
    
    print("--- Test Başlıyor ---")
    tester._process_slave_sync(sender)
    print("--- Test Bitti ---")

if __name__ == "__main__":
    run_test()
