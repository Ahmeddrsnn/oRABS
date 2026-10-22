"""
Quick Test Script for RFID NVS Sync
Tests: Slave RFID assignment → PC query → Response validation
"""

import sys
import time
sys.path.append('src')

from core.esp32_comm import ESP32Communicator

def main():
    print("=" * 60)
    print("RFID NVS SYNC TEST")
    print("=" * 60)
    
    # Initialize
    esp = ESP32Communicator()
    
    # Step 1: Connect to Master (COM13)
    print("\n[STEP 1] Master'a bağlanılıyor (COM13)...")
    if not esp.connect("COM13"):
        print("❌ HATA: Master'a bağlanılamadı!")
        return
    
    print("✅ Master bağlandı")
    time.sleep(2)
    
    # Step 2: Get slave list
    print("\n[STEP 2] Slave listesi alınıyor...")
    esp.get_slave_list()
    time.sleep(3)  # Wait for response
    
    if not esp.slave_devices:
        print("❌ HATA: Slave bulunamadı!")
        print("\nŞimdi yapmanız gerekenler:")
        print("1. Slave (COM11) boot log'dan MAC adresini alın")
        print("2. Master'da: addslave TestAparati MAC_ADRESI")
        return
    
    slave_name = esp.slave_devices[0]['name']
    print(f"✅ Slave bulundu: {slave_name}")
    
    # Step 3: Query new RFIDs
    print(f"\n[STEP 3] {slave_name}'dan yeni RFID'ler sorgulanıyor...")
    print(f"Komut: send {slave_name} {{\"cmd\":\"GET_NEW_RFIDS\"}}")
    
    response = esp.query_new_rfids(slave_name)
    print(f"\nCevap:\n{response}")
    
    # Step 4: Instructions for user
    print("\n" + "=" * 60)
    print("MANUEL ADIMLAR:")
    print("=" * 60)
    print("1. Slave'de (COM11) RFID okutun veya kaydedin:")
    print("   Örnek: ASSIGN:0x004FD0CF:1")
    print("\n2. Bu script'i tekrar çalıştırın")
    print("\n3. Yeni RFID listesini göreceksiniz:")
    print('   [{"rfid":"0x004FD0CF","port":1,"name":"...","admin":false}]')
    print("\n4. PC'de parametreleri gönderdikten sonra flag'i temizleyin:")
    print(f"   esp.clear_new_rfid_flag('{slave_name}', '0x004FD0CF')")
    print("=" * 60)
    
    # Cleanup
    esp.disconnect()
    print("\n✅ Test tamamlandı")

if __name__ == "__main__":
    main()
