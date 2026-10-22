"""RFID normalize + batch port status güncelleme doğrulaması (bug 2026-08-03).

Senaryolar:
  A) normalize_rfid: '0x00DA0DAE'/'da0dae'/' 0X00DA0DAE ' → 'DA0DAE'.
  B) batch_ports.rfid_tag='0x00DA0DAE' iken cihaz formatı 'DA0DAE' ile
     update_batch_port_status → PASS yazılır (eski kod eşleşemiyordu).
  C) Ters yön: satır 'DA0DAE', gelen '0x00DA0DAE' → yine eşleşir.
  D) Eşleşmeyen RFID → False döner (yanlış satır güncellenmez).
  E) bridge._check_ports_completed normalize eşleşmeyle True döner.

Komut: python _verify_rfid_match.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def main():
    print("=" * 60)
    print("RFID normalize + batch port status dogrulamasi")
    print("=" * 60)

    from core.database import Database, normalize_rfid

    # ── A) normalize ──
    print("\n[A] normalize_rfid")
    assert normalize_rfid('0x00DA0DAE') == 'DA0DAE'
    assert normalize_rfid('da0dae') == 'DA0DAE'
    assert normalize_rfid(' 0X00DA0DAE ') == 'DA0DAE'
    assert normalize_rfid('0xDA2C53') == 'DA2C53'
    assert normalize_rfid('') == ''
    assert normalize_rfid(None) == ''
    print("    tum formatlar 'DA0DAE' OK")

    db_path = tempfile.mktemp(suffix='.db')
    db = Database(db_path)
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO glove_ports (name, x_pos, y_pos, rfid_tag) VALUES ('P1', 1, 1, '0x00DA0DAE')")
    gp1 = cur.lastrowid
    cur.execute("INSERT INTO glove_ports (name, x_pos, y_pos, rfid_tag) VALUES ('P2', 2, 2, 'DA2C53')")
    gp2 = cur.lastrowid
    conn.commit()
    db.close()

    bid = db.create_batch('RFID-TEST', 1)
    db.add_ports_to_batch(bid, [
        {'port_id': gp1, 'rfid_tag': '0x00DA0DAE'},   # PC formatı
        {'port_id': gp2, 'rfid_tag': 'DA2C53'},       # kısa format
    ])
    # Test kaydı (zaman kıyası için) — uygulamanın kendi API'siyle
    tid = db.create_test_record({
        'test_id': 'T-1',
        'operator_id': 1,
        'glove_batch_number': 'DA0DAE',   # cihaz (kısa) formatı
        'glove_type': 'SIM',
        'test_start_time': datetime.now().isoformat(),
        'target_pressure': 0,
        'target_temperature': 25,
        'test_duration': 60,
        'test_status': 'COMPLETED',
    })
    assert tid, "test kaydi olusturulamadi"

    # ── B) Cihaz formatı 'DA0DAE' → PC satırı '0x00DA0DAE' güncellenir ──
    print("\n[B] cihaz 'DA0DAE' -> satir '0x00DA0DAE'")
    ok = db.update_batch_port_status(bid, 'DA0DAE', 'PASS', test_record_id=tid)
    assert ok, "guncelleme basarisiz!"
    det = db.get_batch_details(bid)
    st = {p['port_id']: p['status'] for p in det['ports']}
    assert st[gp1] == 'PASS', st
    assert st[gp2] == 'PENDING', "yanlis satir guncellenmis!"
    print(f"    P1=PASS, P2=PENDING OK")

    # ── C) Ters yön: satır kısa, gelen uzun format ──
    print("\n[C] gelen '0x00DA2C53' -> satir 'DA2C53'")
    ok = db.update_batch_port_status(bid, '0x00DA2C53', 'FAIL')
    assert ok
    det = db.get_batch_details(bid)
    st = {p['port_id']: p['status'] for p in det['ports']}
    assert st[gp2] == 'FAIL', st
    print("    P2=FAIL OK")

    # ── D) Eşleşmeyen RFID ──
    print("\n[D] eslesmeyen RFID")
    ok = db.update_batch_port_status(bid, 'FFFFFF', 'PASS')
    assert not ok, "olmayan RFID True dondu!"
    print("    False dondu OK")

    # ── E) bridge._check_ports_completed normalize ──
    print("\n[E] bridge batch_complete normalize")
    from core.auth import AuthManager
    from core.audit import AuditManager
    from core.batch_manager import BatchManager
    from core.weidmuller_bridge import WeidmullerBridge
    auth = AuthManager(db); auth.login('admin', 'Admin123!')
    audit = AuditManager(db, auth)
    bm = BatchManager(db, auth, audit)
    bridge = WeidmullerBridge(db, auth, audit, bm)
    # ORABS port 1 → PC formatlı RFID; test kaydı kısa formatlı (yukarıda)
    conn = db.connect(); cur = conn.cursor()
    cur.execute("UPDATE oraps_port_labels SET rfid_tag='0x00DA0DAE' WHERE port_index=1")
    _past = (datetime.now() - timedelta(minutes=5)).isoformat()
    cur.execute("UPDATE active_batch SET started_at=?, status='running' WHERE id=1", (_past,))
    conn.commit(); db.close()
    assert bridge._check_ports_completed([1]) is True, \
        "normalize eslesme ile tamamlandi sayilmaliydi"
    print("    '0x00DA0DAE' portu, 'DA0DAE' test kaydiyla tamamlandi sayildi OK")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
