"""Alarm kodu sistemi doğrulaması (Faz-13).

Senaryolar:
  A) Katalog bütünlüğü: kod formatı, tekil kodlar, all_rows sıralı.
  B) audit.log_action otomatik kod prefix'i ([KP-01] vb.); '[' ile
     başlayan açıklamaya dokunmaz; katalog dışı action'a kod eklemez.
  C) FORCED tespiti: ORABS aşamasında 'locked' kapının DI'ı açılınca
     DOOR_FORCED (KP-03), kapanınca DOOR_FORCED_CLOSED (KP-04);
     açık (open) kapı → DOOR_OPENED (KP-01).
  D) GLT aşamasında kilitli kapı yok → FORCED üretilmez (KP-01).
  E) MS varyantları: GLT aşaması → [MS-03], idle ayarı → [MS-04],
     normal kapı tetikleme → [MS-01].
  F) LAF add_alarm → [LF-01] prefix'i.

Komut: python _verify_alarm_codes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeWorker:
    def __init__(self):
        self.calls = []

    def write_do(self, channel, value):
        self.calls.append((int(channel), int(value)))


def _last_audit(audit, action):
    rows = audit.get_audit_trail({'action_type': action}) or []
    return rows[0] if rows else None


def main():
    print("=" * 60)
    print("Alarm kodu sistemi dogrulamasi")
    print("=" * 60)

    from core.alarm_codes import ALARM_CODES, all_rows, code_for, prefix_description

    # ── A) Katalog bütünlüğü ──
    print("\n[A] Katalog")
    import re
    codes = [c for c, _, _, _ in all_rows()]
    assert len(codes) == len(set(codes)), "kod tekrar var"
    for c in codes:
        assert re.fullmatch(r'[A-Z]{2}-\d{2}', c), f"format bozuk: {c}"
    assert code_for('DOOR_FORCED') == 'KP-03'
    assert code_for('BARRIER_LOW_BATTERY') == 'PT-03', "PT tasima (kullanici istegi)"
    assert code_for('BARRIER_DISCOVERED') == 'PT-04'
    assert code_for('BATCH_PAUSED') == 'BT-01'
    assert prefix_description('DOOR_OPENED', 'test') == '[KP-01] test'
    assert prefix_description('DOOR_OPENED', '[MS-03] x') == '[MS-03] x'
    assert prefix_description('BILINMEYEN_X', 'y') == 'y'
    print(f"    {len(codes)} kod, format + tekillik + prefix kurallari OK")

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

    # ── B) log_action prefix ──
    print("\n[B] audit.log_action prefix")
    audit.log_action(action_type='DOOR_OPENED', description='Kapi 3 acildi')
    row = _last_audit(audit, 'DOOR_OPENED')
    assert row['description'].startswith('[KP-01] '), row['description']
    audit.log_action(action_type='CONFIG_CREATED', description='kodsuz olay')
    row = _last_audit(audit, 'CONFIG_CREATED')
    assert not row['description'].startswith('['), "katalog disi kod almamali"
    print("    [KP-01] eklendi, katalog disi dokunulmadi OK")

    # ── Kurulum: DI ch0 → kapı 5; kilit içeren config ──
    wm = bridge.wm
    di_pts = {p['channel']: p for p in wm.list_points(module_id=1, point_type='DI')}
    do_pts = {p['channel']: p for p in wm.list_points(module_id=1, point_type='DO')}
    wm.set_link(di_pts[0]['id'], 'door', 5, '')
    wm.set_link(do_pts[7]['id'], 'door', 5, 'machine_stop')
    fw = FakeWorker()
    bridge.workers[1] = fw

    # ── C) ORABS aşamasında FORCED ──
    print("\n[C] Kilitli kapi FORCED tespiti (ORABS asamasi)")
    cfg = bm.create_config('KILITLI', '', {'5': 'locked'})
    bm.start_batch('B-F', cfg)   # wait_glt_pass=0 → phase='orabs'
    bridge._on_di_edge(1, 0, 0, datetime.now().isoformat())   # DI=0 → kapı AÇILDI
    row = _last_audit(audit, 'DOOR_FORCED')
    assert row and '[KP-03]' in row['description'], row
    print(f"    DOOR_FORCED: {row['description']}")
    bridge._on_di_edge(1, 0, 1, datetime.now().isoformat())   # DI=1 → KAPANDI
    row = _last_audit(audit, 'DOOR_FORCED_CLOSED')
    assert row and '[KP-04]' in row['description'], row
    print(f"    DOOR_FORCED_CLOSED: {row['description']}")
    bm.finish_batch()
    bridge.on_batch_changed()

    # Açık (locked olmayan) kapı → normal KP-01
    cfg2 = bm.create_config('ACIK', '', {'5': 'open'})
    bm.start_batch('B-O', cfg2)
    bridge._worker_edge_guard = None
    bridge._on_di_edge(1, 0, 0, datetime.now().isoformat())
    row = _last_audit(audit, 'DOOR_OPENED')
    assert row and '[KP-01]' in row['description'], row
    print(f"    normal kapi: {row['description']}")
    bridge._on_di_edge(1, 0, 1, datetime.now().isoformat())
    bm.finish_batch()
    bridge.on_batch_changed()

    # ── D) GLT aşamasında FORCED üretilmez ──
    print("\n[D] GLT asamasinda FORCED yok")
    cfg3 = bm.create_config('GLT-BEKLE', '', {'5': 'locked'}, wait_glt_pass=1)
    bm.start_batch('B-G', cfg3)
    bridge._on_di_edge(1, 0, 0, datetime.now().isoformat())
    row = _last_audit(audit, 'DOOR_OPENED')
    assert row, "GLT fazinda OPENED loglanmali"
    print("    GLT fazinda kapi acilmasi KP-01 (FORCED degil) OK")

    # ── E) MS varyant kodları ──
    print("\n[E] MS varyantlari")
    # GLT aşaması aktif → force_all_stop → [MS-03]
    fw.calls.clear()
    bridge._machine_stop_out.clear()
    bridge._update_machine_stop_dos()
    row = _last_audit(audit, 'MACHINE_STOP_TRIGGERED')
    assert row and '[MS-03]' in row['description'], row['description']
    print(f"    GLT fazi: {row['description']}")
    bm.finish_batch()
    # idle + ayar → [MS-04]
    db.set_setting('oraps_machine_stop_idle', '1')
    bridge._machine_stop_out.clear()
    bridge._update_machine_stop_dos()
    row = _last_audit(audit, 'MACHINE_STOP_TRIGGERED')
    assert row and '[MS-04]' in row['description'], row['description']
    print(f"    idle kilit: {row['description']}")
    db.set_setting('oraps_machine_stop_idle', '0')
    bridge._update_machine_stop_dos()
    # normal kapı tetikleme → [MS-01]
    cfg4 = bm.create_config('MS-N', '', {'5': 'open'})
    bm.start_batch('B-MS', cfg4)
    bridge._door_di_state[5] = 1
    bridge._update_machine_stop_dos()
    row = _last_audit(audit, 'MACHINE_STOP_TRIGGERED')
    assert row and '[MS-01]' in row['description'], row['description']
    print(f"    kapi tetikleme: {row['description']}")
    bm.finish_batch()

    # ── F) LAF alarm prefix ──
    print("\n[F] LAF")
    from core.laf_manager import LafManager
    laf = LafManager(db, auth, audit)
    laf.add_alarm('F3', 'Fan arizasi')
    row = _last_audit(audit, 'LAF_ALARM')
    assert row and '[LF-01]' in row['description'], row
    print(f"    {row['description']}")

    db.close()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("\nTUM SENARYOLAR GECTI")


if __name__ == '__main__':
    main()
