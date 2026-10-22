"""IO alarm simülasyonu — her alarm TEK SEFER tetiklenir (donanımsız).

Geçici DB + FakeWorker kullanır; gerçek veritabanına/donanıma dokunmaz.
Bridge'in gerçek DI-edge işleme kodu çalıştırılır (weidmuller_bridge),
yani üretilen audit kayıtları uygulamadakiyle birebir aynıdır.

Senaryo sırası (her biri 1 kez):
  1. KP-01  Kapı açıldı            (serbest kapı 6, DI → 0)
  2. KP-02  Kapı kapatıldı         (serbest kapı 6, DI → 1)
  3. KP-03  Kilitli kapı açıldı    (kilitli kapı 5, DI → 0)
  4. KP-04  Kilitli kapı kapatıldı (kilitli kapı 5, DI → 1)
  5. IB-01  Işık bariyeri tetiklendi (bariyer DI → 1) [IB-02 interlock notu
            batch çalıştığı için otomatik düşer]
  6. AS-01  ACİL STOP basıldı      (estop DI → 0, NC kontak)
  7. AS-02  Acil stop serbest      (estop DI → 1)

Komut: python _sim_io_alarms.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeWorker:
    """write_do çağrılarını kabul eden sahte worker (Modbus yok)."""
    def __init__(self):
        self.calls = []

    def write_do(self, channel, value):
        self.calls.append((int(channel), int(value)))


def main():
    print("=" * 64)
    print("IO ALARM SIMULASYONU — her alarm 1 kez (donanimsiz)")
    print("=" * 64)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager
    from core.weidmuller_bridge import WeidmullerBridge

    db = Database(db_path)
    auth = AuthManager(db)
    assert auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)
    bridge = WeidmullerBridge(db, auth, audit, bm)
    bridge.workers[1] = FakeWorker()

    # ── Kurulum: DI kanalları → kapı 6 (serbest), kapı 5 (kilitli),
    #    bariyer B1, acil stop ─────────────────────────────────────
    wm = bridge.wm
    di = {p['channel']: p for p in wm.list_points(module_id=1, point_type='DI')}
    wm.set_link(di[0]['id'], 'door', 6, '')       # serbest kapı
    wm.set_link(di[1]['id'], 'door', 5, '')       # kilitli kapı
    barrier_id = bm.add_barrier('SIM-Bariyer', door_indices=[5, 6])
    wm.set_link(di[2]['id'], 'barrier', barrier_id, '')
    wm.set_link(di[3]['id'], 'estop', 1, '')      # seed'li Ana Acil Stop

    # Kapı adları (raporda okunaklı olsun)
    bm.update_door_label(5, label='Kilitli Kapak (SIM)')
    bm.update_door_label(6, label='Serbest Kapak (SIM)')

    # ORABS aşamalı batch: kapı 5 kilitli, kapı 6 açık
    cfg = bm.create_config('SIM-CFG', 'simülasyon', {'5': 'locked', '6': 'open'})
    bm.start_batch('SIM-BATCH', cfg)
    bridge.on_batch_changed()
    t0 = datetime.now().isoformat()

    def edge(ch, state, label):
        print(f"  -> {label}")
        bridge._on_di_edge(1, ch, state, datetime.now().isoformat())
        time.sleep(0.05)   # audit timestamp sırası netleşsin

    print("\n[SIM] Tek seferlik tetiklemeler:")
    # DI konvansiyonu: 1 = kapalı/temas var, 0 = açık/temas yok (NC)
    edge(0, 0, "1) Serbest kapi ACILDI   (KP-01 bekleniyor)")
    edge(0, 1, "2) Serbest kapi KAPANDI  (KP-02 bekleniyor)")
    edge(1, 0, "3) Kilitli kapi ACILDI   (KP-03 bekleniyor)")
    edge(1, 1, "4) Kilitli kapi KAPANDI  (KP-04 bekleniyor)")
    edge(2, 1, "5) Isik bariyeri KESILDI (IB-01 bekleniyor)")
    edge(3, 0, "6) ACIL STOP BASILDI     (AS-01 bekleniyor)")
    edge(3, 1, "7) Acil stop SERBEST     (AS-02 bekleniyor)")

    # ── Sonuç: simülasyon süresince oluşan audit kayıtları ──
    rows = audit.get_audit_trail({'date_from': t0}) or []
    rows = sorted(rows, key=lambda r: r.get('timestamp') or '')
    print("\n" + "=" * 64)
    print("OLUSAN AUDIT KAYITLARI (alarm kodlariyla):")
    print("=" * 64)
    shown = 0
    for r in rows:
        at = r.get('action_type') or ''
        if at in ('BATCH_STARTED', 'CONFIG_CREATED', 'DOOR_LABEL_UPDATED',
                  'BARRIER_ADDED', 'IO_POINT_LINK'):
            continue   # kurulum gürültüsü
        ts = (r.get('timestamp') or '')[11:19]
        print(f"  {ts}  {at:<26} {r.get('description')}")
        shown += 1
    print(f"\nToplam {shown} alarm/olay kaydi.")

    # Beklenen kodların hepsi düştü mü?
    all_desc = ' | '.join((r.get('description') or '') for r in rows)
    expected = ['[KP-01]', '[KP-02]', '[KP-03]', '[KP-04]',
                '[IB-01]', '[AS-01]', '[AS-02]']
    missing = [c for c in expected if c not in all_desc]
    if missing:
        print(f"\nUYARI — eksik kodlar: {missing}")
        sys.exit(1)
    print("TUM BEKLENEN ALARM KODLARI URETILDI ✓")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
