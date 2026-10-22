"""IO alarm simülasyonu — UYGULAMA İÇİNDE GÖRÜNÜR sürüm.

GERÇEK veritabanına (database/glove_test.db) her alarmdan BİR audit kaydı
yazar. Uygulama AÇIKKEN çalıştırın:
  • Ana sayfa "Son Olaylar" listesi 5 sn içinde kayıtları gösterir.
  • Kritik olanlar (KP-03, IB-01, AS-01) üstteki kırmızı ALARM BANNER'ını
    yakar (banner son 5 dakikadaki kritik olaylara bakar).

Notlar:
  • Kayıtlar "(SİMÜLASYON)" etiketlidir; audit geçmişinde kalıcıdır
    (21 CFR — audit silinmez). Donanıma/batch durumuna DOKUNMAZ.
  • 3D kapı boyaması değişmez (o, uygulama içindeki canlı DI sinyalinden
    beslenir; ayrı prosesten tetiklenemez).

Komut: python _sim_io_alarms_app.py
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

DB_PATH = os.path.join(HERE, 'database', 'glove_test.db')


def main():
    print("=" * 64)
    print("IO ALARM SIMULASYONU (UYGULAMA GORUNUR) — gercek DB'ye yazar")
    print("=" * 64)
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        sys.exit(1)

    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager

    db = Database(DB_PATH)
    auth = AuthManager(db)          # login yok → kayıtlar 'SYSTEM' kullanıcısıyla
    audit = AuditManager(db, auth)

    events = [
        # (action_type, tablo, record_id, açıklama)  — kod prefix'ini
        # audit.log_action alarm kataloğundan otomatik ekler.
        ('DOOR_OPENED',        'oraps_door_labels', 6,
         "Serbest Kapak açıldı (SİMÜLASYON)"),
        ('DOOR_CLOSED',        'oraps_door_labels', 6,
         "Serbest Kapak kapatıldı (SİMÜLASYON)"),
        ('DOOR_FORCED',        'oraps_door_labels', 5,
         "Kilitli Kapak zorlandı (SİMÜLASYON)"),
        ('DOOR_FORCED_CLOSED', 'oraps_door_labels', 5,
         "Kilitli Kapak kapatıldı — kilitliyken açılmıştı (SİMÜLASYON)"),
        ('BARRIER_TRIGGERED',  'light_barriers', 1,
         "Işık bariyeri BLOKE (SİMÜLASYON)"),
        ('ESTOP_TRIGGERED',    'oraps_estop_buttons', 1,
         "Acil stop butonu BASILDI (SİMÜLASYON)"),
        ('ESTOP_RELEASED',     'oraps_estop_buttons', 1,
         "Acil stop butonu serbest bırakıldı (SİMÜLASYON)"),
    ]

    print("\nYazilan kayitlar:")
    for action, table, rid, desc in events:
        audit.log_action(
            action_type=action,
            table_name=table,
            record_id=rid,
            description=desc,
            category='ORAPS',
        )
        print(f"  {action:<22} {desc}")
        time.sleep(0.2)   # Son Olaylar'da sıralı görünsün

    db.close()
    print("\nTAMAM — uygulama ACIKSA:")
    print("  • Son Olaylar listesi ~5 sn içinde güncellenir")
    print("  • KP-03 / IB-01 / AS-01 kırmızı alarm banner'ını yakar (5 dk pencere)")
    print("  • Banner'ı 'Tamam' ile kapatabilirsiniz")


if __name__ == '__main__':
    main()
