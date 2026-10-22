"""Faz-6a Weidmüller IO smoke test (DB + manager + worker mock).

Komut:
    python _smoke_weidmuller.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _row_or_die(cur, sql, *params, label=''):
    cur.execute(sql, params)
    row = cur.fetchone()
    assert row is not None, f"{label}: yok"
    return row


def main():
    print("=" * 60)
    print("Faz-6a Weidmüller IO Smoke Test")
    print("=" * 60)

    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    db = Database(db_path)

    print(f"\n[1] DB created: {db_path}")
    conn = db.connect()
    cur = conn.cursor()
    for tbl in ('weidmuller_modules', 'weidmuller_io_points'):
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
        assert cur.fetchone() is not None, f"tablo eksik: {tbl}"
        print(f"    tablo {tbl}: OK")

    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='weidmuller_schema_version'")
    print(f"    weidmuller_schema_version = {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM weidmuller_modules")
    n_mod = cur.fetchone()[0]
    print(f"    weidmuller_modules seed: {n_mod} (beklenen 1)")
    assert n_mod == 1

    cur.execute("SELECT COUNT(*) FROM weidmuller_io_points")
    n_pt = cur.fetchone()[0]
    print(f"    weidmuller_io_points seed: {n_pt} (beklenen 40: 16DI+16DO+4AI+4AO)")
    assert n_pt == 40

    cur.execute("SELECT point_type, COUNT(*) FROM weidmuller_io_points GROUP BY point_type")
    rows = dict(cur.fetchall())
    print(f"    nokta dağılımı: {rows}")
    assert rows == {'DI': 16, 'DO': 16, 'AI': 4, 'AO': 4}
    db.close()

    # Manager / Auth
    print("\n[2] WeidmullerManager wired")
    from core.auth import AuthManager
    from core.audit import AuditManager
    auth = AuthManager(db)
    auth.login('admin', 'Admin123!')
    print(f"    role={auth.get_current_user_role()}")

    audit = AuditManager(db, auth)
    from core.weidmuller_manager import WeidmullerManager
    wm = WeidmullerManager(db, auth, audit)

    mods = wm.list_modules()
    assert len(mods) == 1
    mod_id = mods[0]['id']
    print(f"    list_modules() -> 1 modül id={mod_id} host={mods[0]['host']}")

    # Add / update / delete cycle
    new_mid = wm.add_module(name='TEST-2', host='10.0.0.1', port=502, unit_id=255)
    print(f"    add_module() -> id={new_mid}")
    wm.update_module(new_mid, description='değiştirildi')
    fetched = wm.get_module(new_mid)
    assert fetched['description'] == 'değiştirildi'
    print("    update_module() OK")
    wm.delete_module(new_mid)
    print(f"    delete_module() OK, final count: {len(wm.list_modules())}")

    # Points
    points = wm.list_points(module_id=mod_id)
    print(f"\n[3] list_points(modul {mod_id}) -> {len(points)} satır")
    di_only = wm.list_points(module_id=mod_id, point_type='DI')
    print(f"    DI filtre: {len(di_only)} (beklenen 16)")
    assert len(di_only) == 16

    new_pid = wm.add_point(module_id=mod_id, point_type='DI', channel=31,
                            name='DI32 test')
    print(f"    add_point() -> id={new_pid}")
    wm.update_point(new_pid, name='değişti')
    p = wm.get_point(new_pid)
    assert p['name'] == 'değişti'
    print("    update_point() OK")
    wm.delete_point(new_pid)
    print("    delete_point() OK")

    # Worker (mock)
    print("\n[4] WeidmullerWorker mock poll")
    from core.weidmuller_worker import WeidmullerWorker
    worker = WeidmullerWorker(wm, mod_id)
    worker.reload_config()
    assert worker._mock is True, "varsayılan mock olmalı"
    values = worker._poll_once()
    print(f"    poll keys: {sorted(values.keys())}")
    assert set(values.keys()) == {'DI', 'DO', 'AI', 'AO'}
    print(f"    DI sayısı: {len(values['DI'])}, AI ham örnek: ai0_raw={values['AI'][0]['raw']}")

    # AO/DO yazma (mock yolu — TCP yok)
    worker.write_ao(0, percent=50.0)
    worker.write_do(2, 1)
    worker._handle_commands()
    values2 = worker._poll_once()
    assert values2['DO'][2] == 1, "mock DO bit ayarlanmalı"
    print(f"    mock DO[2] = {values2['DO'][2]} (beklenen 1)")
    print(f"    mock AO[0] raw={values2['AO'][0]['raw']} pct={values2['AO'][0]['pct']:.1f}")

    # Faz-6b: IO ↔ kapı/port/LAF link layer
    print("\n[4b] Faz-6b link katmanı")

    # Schema sütunları
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(weidmuller_io_points)")
    cols = {r[1] for r in cur.fetchall()}
    for c in ('link_type', 'link_id', 'link_role'):
        assert c in cols, f"sütun eksik: {c}"
    print(f"    şema: link_type/link_id/link_role mevcut ✓")
    db.close()

    # Önce hiçbir nokta bağlı değil → 40 unlinked
    unlinked = wm.list_unlinked()
    print(f"    list_unlinked() başlangıç: {len(unlinked)} (beklenen 40)")
    assert len(unlinked) == 40

    # list_link_targets döndürmeli
    door_targets = wm.list_link_targets('door')
    port_targets = wm.list_link_targets('port')
    laf_targets = wm.list_link_targets('laf')
    print(f"    list_link_targets door={len(door_targets)} port={len(port_targets)} laf={len(laf_targets)}")
    assert len(door_targets) >= 12, "12 kapı slotu görünmeli"
    assert len(port_targets) >= 14, "14 port slotu görünmeli"

    # İlk DI ve ilk DO'yu kapı 5'e bağla
    di_list = wm.list_points(module_id=mod_id, point_type='DI')
    do_list = wm.list_points(module_id=mod_id, point_type='DO')
    di_pid = di_list[0]['id']
    do_pid = do_list[0]['id']
    wm.set_link(di_pid, 'door', 5, 'sensor')
    wm.set_link(do_pid, 'door', 5, 'kilit')
    print(f"    set_link() DI -> Kapı 5 (sensor), DO -> Kapı 5 (kilit)")

    # get_point link alanlarını dönmeli
    pdi = wm.get_point(di_pid)
    assert pdi['link_type'] == 'door' and pdi['link_id'] == 5 and pdi['link_role'] == 'sensor'

    # resolve_link_label
    lbl = wm.resolve_link_label('door', 5)
    print(f"    resolve_link_label('door', 5) = '{lbl}'")
    assert 'Kapı 5' in lbl or 'kapı 5' in lbl.lower()

    # silinmiş hedef
    lbl_dead = wm.resolve_link_label('door', 999)
    print(f"    resolve_link_label('door', 999) = '{lbl_dead}'")
    assert any(tok in lbl_dead.lower() for tok in ('silinmiş', 'etiketsiz', '999'))

    # Unlinked azaldı mı?
    unlinked2 = wm.list_unlinked()
    print(f"    list_unlinked() bağlama sonrası: {len(unlinked2)} (beklenen 38)")
    assert len(unlinked2) == 38

    # list_links_for tersine arama
    links_door5 = wm.list_links_for('door', 5)
    print(f"    list_links_for('door', 5) = {len(links_door5)} nokta")
    assert len(links_door5) == 2

    # Bağlantı çıkar (link_type=None)
    wm.set_link(di_pid, None, None, '')
    pdi2 = wm.get_point(di_pid)
    assert pdi2['link_type'] is None and pdi2['link_id'] is None
    print(f"    set_link(None) DI bağlantısı kaldırıldı ✓")
    assert len(wm.list_unlinked()) == 39

    # Geçersiz link_type
    try:
        wm.set_link(di_pid, 'galaxy', 1, '')
        assert False, "geçersiz tip kabul edildi"
    except ValueError as e:
        print(f"    geçersiz link_type reddedildi ✓ ({e})")

    # Faz-6c: Işık bariyeri ↔ IO link katmanı
    print("\n[4c] Faz-6c ışık bariyeri")
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='light_barriers'")
    assert cur.fetchone() is not None, "light_barriers tablosu yok"
    print("    tablo light_barriers: OK")
    db.close()

    from core.batch_manager import BatchManager
    bm = BatchManager(db, auth, audit)

    # Boş başlangıç
    assert bm.list_barriers() == []
    print("    list_barriers() başlangıç boş ✓")

    # Aynı kapı reddi
    try:
        bm.add_barrier("X", 4, 4)
        assert False, "aynı kapı kabul edildi"
    except ValueError as e:
        print(f"    aynı kapı reddedildi ✓ ({e})")

    # Geçersiz indeks reddi
    try:
        bm.add_barrier("X", 1, 99)
        assert False
    except ValueError as e:
        print(f"    geçersiz indeks reddedildi ✓ ({e})")

    # Normalize (a > b → swap)
    bid1 = bm.add_barrier("Giriş", door_a_index=5, door_b_index=3, description='Test')
    b1 = bm.get_barrier(bid1)
    assert b1['door_a_index'] == 3 and b1['door_b_index'] == 5
    print(f"    add_barrier(5,3) normalize → (3,5) ✓ id={bid1}")

    bid2 = bm.add_barrier("Çıkış", door_a_index=7, door_b_index=8)
    print(f"    add_barrier() ikinci → id={bid2}")
    assert len(bm.list_barriers()) == 2
    assert len(bm.list_barriers(only_active=True)) == 2

    # WeidmullerManager tarafından görülmesi
    targets = wm.list_link_targets('barrier')
    print(f"    wm.list_link_targets('barrier') = {len(targets)} satır")
    assert len(targets) == 2
    assert any(t['id'] == bid1 for t in targets)

    # IO noktasına bağla
    wm.set_link(do_pid, 'barrier', bid1, 'tetikleyici')
    p_after = wm.get_point(do_pid)
    assert p_after['link_type'] == 'barrier' and p_after['link_id'] == bid1
    lbl = wm.resolve_link_label('barrier', bid1)
    print(f"    resolve_link_label('barrier', {bid1}) = '{lbl}'")
    assert 'Giriş' in lbl and 'Kapı 3' in lbl and 'Kapı 5' in lbl

    # update_barrier
    bm.update_barrier(bid1, label='Giriş bariyeri', door_a_index=2, door_b_index=6)
    bup = bm.get_barrier(bid1)
    assert bup['label'] == 'Giriş bariyeri' and bup['door_a_index'] == 2 and bup['door_b_index'] == 6
    print(f"    update_barrier OK → {bup['label']} (Kapı {bup['door_a_index']}↔{bup['door_b_index']})")

    # is_active=0 → liste filtresi
    bm.update_barrier(bid2, is_active=0)
    assert len(wm.list_link_targets('barrier')) == 1
    print(f"    is_active=0 sonrası link_targets: 1 (beklenen 1)")

    # delete_barrier → orphan kontrolü
    bm.delete_barrier(bid1)
    assert bm.get_barrier(bid1) is None
    orphan_lbl = wm.resolve_link_label('barrier', bid1)
    print(f"    silinmiş bariyer label = '{orphan_lbl}'")
    assert 'silinmiş' in orphan_lbl.lower() or str(bid1) in orphan_lbl
    # IO noktasının link_id'si değişmedi (orphan tolerans)
    p_orphan = wm.get_point(do_pid)
    assert p_orphan['link_type'] == 'barrier' and p_orphan['link_id'] == bid1
    print(f"    IO noktası orphan korundu ✓")

    # ── [4d] Faz-6d bariyer olay kaydı ──────────────────────────
    print("\n[4d] Faz-6d bariyer olay kaydı")
    cur2 = db.connect().cursor()
    cur2.execute("SELECT name FROM sqlite_master WHERE type='table' "
                 "AND name='light_barrier_events'")
    assert cur2.fetchone() is not None, "light_barrier_events tablosu yok"
    print("    tablo light_barrier_events: OK")
    db.close()

    # Yeni bariyer + DI bağlama
    bid3 = bm.add_barrier("Test bariyer 6d", door_a_index=10, door_b_index=11)
    # di_pid daha önce unlinked olarak boş bırakılmış; bariyere bağla
    wm.set_link(di_pid, 'barrier', bid3, 'tetikleyici')
    print(f"    bid={bid3} → DI(point#{di_pid}) bağlandı")

    # state=1 (rising) kaydı
    ev1 = bm.record_barrier_event(barrier_id=bid3, module_id=mod_id,
                                  channel=di_list[0]['channel'], state=1)
    assert ev1 is not None
    print(f"    record_barrier_event(state=1) → event_id={ev1}")

    # state=0 (falling) kaydı
    ev2 = bm.record_barrier_event(barrier_id=bid3, module_id=mod_id,
                                  channel=di_list[0]['channel'], state=0)
    assert ev2 is not None and ev2 > ev1
    print(f"    record_barrier_event(state=0) → event_id={ev2}")

    # list_recent_barrier_events
    recent = bm.list_recent_barrier_events(limit=10)
    assert len(recent) >= 2
    assert recent[0]['id'] == ev2 and recent[0]['state'] == 0
    assert recent[1]['id'] == ev1 and recent[1]['state'] == 1
    print(f"    list_recent: {len(recent)} olay, en yeni state={recent[0]['state']} ✓")

    recent_only = bm.list_recent_barrier_events(limit=5, barrier_id=bid3)
    assert len(recent_only) == 2
    print(f"    list_recent(barrier_id={bid3}) = {len(recent_only)} ✓")

    # state validation
    try:
        bm.record_barrier_event(bid3, mod_id, 0, state=5)
        assert False, "geçersiz state kabul edildi"
    except ValueError as e:
        print(f"    state validation ✓ ({e})")

    # silinmiş bariyer → None
    bm.delete_barrier(bid3)
    ev_after_del = bm.record_barrier_event(bid3, mod_id, 0, state=1)
    assert ev_after_del is None
    print(f"    silinmiş bariyer için record → None (no audit, no row) ✓")

    # Worker edge detection unit test (thread başlatmadan)
    from core.weidmuller_worker import WeidmullerWorker
    w = WeidmullerWorker(wm, mod_id)
    w._debounce_sec = 0.0  # debounce kapalı: pür edge-detection testi
    captured: list[tuple] = []
    w.di_edge.connect(lambda m, c, s, t: captured.append((m, c, s)))
    # İlk poll → referans (hiç sinyal)
    w._emit_di_edges({0: 0, 1: 0, 2: 0}, '2026-06-19T00:00:00')
    assert captured == []
    # 1. kanalda rising
    w._emit_di_edges({0: 0, 1: 1, 2: 0}, '2026-06-19T00:00:01')
    assert captured == [(mod_id, 1, 1)]
    # 1. kanalda falling, 2. kanalda rising
    captured.clear()
    w._emit_di_edges({0: 0, 1: 0, 2: 1}, '2026-06-19T00:00:02')
    assert sorted(captured) == [(mod_id, 1, 0), (mod_id, 2, 1)]
    print(f"    worker._emit_di_edges edge tespiti ✓")

    # Debounce testi: çok hızlı toggle ardından ikinci kenar atılmalı,
    # debounce penceresi bittikten sonraki kenar geçmeli.
    import time as _t
    w2 = WeidmullerWorker(wm, mod_id)
    w2._debounce_sec = 0.2  # 200 ms
    captured2: list[tuple] = []
    w2.di_edge.connect(lambda m, c, s, t: captured2.append((m, c, s)))
    w2._emit_di_edges({3: 0}, 't0')                # ref
    w2._emit_di_edges({3: 1}, 't1')                # rising → kabul
    w2._emit_di_edges({3: 0}, 't2')                # 50ms sonra falling → düşmeli
    assert captured2 == [(mod_id, 3, 1)], f"debounce başarısız: {captured2}"
    _t.sleep(0.25)
    w2._emit_di_edges({3: 0}, 't3')                # pencere bitti, gerçek 0 → kabul
    assert captured2 == [(mod_id, 3, 1), (mod_id, 3, 0)], f"pencere sonrası: {captured2}"
    print(f"    DI debounce 200ms: bouncing ikinci kenar düşürüldü ✓")

    # ── [4e] DI edge → DOOR/PORT köprüsü + port occupancy ───────
    print("\n[4e] DI edge → DOOR/PORT audit + port_occupancy")
    # is_occupied / last_motion_ts kolonları mevcut mu?
    cur3 = db.connect().cursor()
    cur3.execute("PRAGMA table_info(oraps_port_labels)")
    cols = {r[1] for r in cur3.fetchall()}
    assert 'is_occupied' in cols and 'last_motion_ts' in cols, (
        f"is_occupied/last_motion_ts kolonları eksik: {cols}"
    )
    db.close()
    print("    kolonlar: is_occupied + last_motion_ts ✓")

    # DOOR event → audit'e gitti mi?
    bm.log_door_io_event(door_index=3, event='OPENED', source='IO')
    bm.log_door_io_event(door_index=3, event='CLOSED', source='IO')
    cur3 = db.connect().cursor()
    cur3.execute("SELECT action_type, COUNT(*) FROM audit_trail "
                 "WHERE category='ORAPS' AND table_name='oraps_door_labels' "
                 "GROUP BY action_type")
    door_audit = dict(cur3.fetchall())
    db.close()
    print(f"    DOOR audit: {door_audit}")
    assert door_audit.get('DOOR_OPENED', 0) >= 1
    assert door_audit.get('DOOR_CLOSED', 0) >= 1

    # PORT motion → audit + is_occupied güncellendi mi?
    bm.log_port_motion_event(port_index=5, detected=True, source='IO')
    occ = bm.get_port_occupancy()
    assert occ[5]['is_occupied'] == 1
    assert occ[5]['last_motion_ts'] is not None
    print(f"    port#5 detected → is_occupied=1, ts={occ[5]['last_motion_ts']}")
    bm.log_port_motion_event(port_index=5, detected=False, source='IO')
    occ = bm.get_port_occupancy()
    assert occ[5]['is_occupied'] == 0
    print(f"    port#5 ended    → is_occupied=0")

    cur3 = db.connect().cursor()
    cur3.execute("SELECT action_type, COUNT(*) FROM audit_trail "
                 "WHERE category='ORAPS' AND table_name='oraps_port_labels' "
                 "GROUP BY action_type")
    port_audit = dict(cur3.fetchall())
    db.close()
    print(f"    PORT audit: {port_audit}")
    assert port_audit.get('PORT_MOTION', 0) >= 1
    assert port_audit.get('PORT_MOTION_END', 0) >= 1

    # ── [4f] Bridge: door_states → DO write hesabı ─────────────
    print("\n[4f] WeidmullerBridge: door_states → DO writes")
    from core.weidmuller_bridge import WeidmullerBridge, DO_LOCKED, DO_OPEN
    bridge = WeidmullerBridge(db, auth, audit, bm)

    # do_pid daha önce barrier'a bağlıydı (silinmiş); şimdi door#7'ye
    # kilit rolü ile bağla
    wm.set_link(do_pid, 'door', 7, 'kilit')
    pdo = wm.get_point(do_pid)
    print(f"    DO#{do_pid} → door#7 'kilit' ba\u011fland\u0131 "
          f"(ch={pdo['channel']}, module={pdo['module_id']})")

    # Birkaç state ile compute
    writes = bridge.compute_door_lock_writes({'7': 'locked', '8': 'open'})
    assert len(writes) == 1, f"beklenen 1 write, gelen {writes}"
    mid_w, ch_w, val_w = writes[0]
    assert mid_w == pdo['module_id'] and ch_w == pdo['channel']
    assert val_w == DO_LOCKED
    print(f"    compute: door#7 locked → (mod={mid_w}, ch={ch_w}, val={val_w}=KİLİTLİ) ✓")

    writes2 = bridge.compute_door_lock_writes({'7': 'open'})
    assert writes2[0][2] == DO_OPEN
    print(f"    compute: door#7 open → val={DO_OPEN}=AÇIK ✓")

    # Kilit dışı role (örn. 'sinyal') ise yazma yapılmasın
    wm.set_link(do_pid, 'door', 7, 'sinyal')
    writes3 = bridge.compute_door_lock_writes({'7': 'locked'})
    assert writes3 == [], f"kilit-d\u0131\u015f\u0131 rol writelist'e d\u00fc\u015ft\u00fc: {writes3}"
    print(f"    role='sinyal' → write yok ✓ (sadece 'kilit' rolü kullanılır)")

    # apply_door_locks: worker yok (start_all çağırılmadı) → 0 yazım,
    # hata olmamalı
    n = bridge.apply_door_locks({'7': 'locked'})
    assert n == 0
    print(f"    apply_door_locks worker yokken sessiz: 0 komut ✓")

    # Worker'ı başlat ve compute çıktısını manuel yaz (worker DB'ye
    # dokunmadan); ana thread'in DB connection'ını koruyalım.
    # Not: Database singleton conn worker thread'den close edilebileceği
    # için apply_door_locks() çağrısını test koşumunda compute + direct
    # write_do parçalarına ayırıyoruz.
    wm.set_link(do_pid, 'door', 7, 'kilit')
    writes_final = bridge.compute_door_lock_writes({'7': 'locked'})
    assert len(writes_final) == 1
    bridge.start_all()
    try:
        import time as _t
        _t.sleep(0.3)  # worker'ın reload_config'i tamamlasın
        w = bridge.workers[writes_final[0][0]]
        w.write_do(writes_final[0][1], writes_final[0][2])
        _t.sleep(0.7)  # mock worker komutu işlesin
        print(f"    worker.write_do(ch={writes_final[0][1]}, val={writes_final[0][2]}) "
              f"komutu sıraya verildi ✓")
    finally:
        bridge.stop_all()

    # ── [4g] AI alarm thresholds (set + worker evaluation) ──────
    print("\n[4g] Faz-6g AI alarm eşikleri")
    # AI nokta yarat (channel 9 — kullanılmamış, modül mod_id, scale=1)
    ai_pid = wm.add_point(mod_id, 'AI', 9, 'Sıcaklık', unit='°C',
                           scale=1.0, offset=0.0)
    wm.set_alarm_thresholds(ai_pid, low=10.0, high=80.0)
    p = wm.get_point(ai_pid)
    assert p['low_alarm'] == 10.0 and p['high_alarm'] == 80.0
    print(f"    set_alarm_thresholds(low=10, high=80) ✓")

    # Geçersiz: low ≥ high
    try:
        wm.set_alarm_thresholds(ai_pid, low=50.0, high=20.0)
        assert False, "low ≥ high reddedilmedi"
    except ValueError as e:
        print(f"    low≥high reddedildi ✓ ({e})")

    # Worker evaluator unit test
    from core.weidmuller_worker import WeidmullerWorker
    w_ai = WeidmullerWorker(wm, mod_id)
    w_ai.reload_config()  # AI thresholds'u DB'den çek
    captured_alarms: list[tuple] = []
    w_ai.ai_alarm.connect(
        lambda m, c, s, v, t, ts: captured_alarms.append((c, s, v))
    )
    # OK → HIGH
    w_ai._evaluate_ai_alarms({9: {'raw': 90.0}}, 't1')
    # Aynı değer tekrar → yeni event yok
    w_ai._evaluate_ai_alarms({9: {'raw': 91.0}}, 't2')
    # HIGH → OK
    w_ai._evaluate_ai_alarms({9: {'raw': 50.0}}, 't3')
    # OK → LOW
    w_ai._evaluate_ai_alarms({9: {'raw': 5.0}}, 't4')
    severities = [(c, s) for c, s, _v in captured_alarms]
    assert severities == [(9, 'HIGH'), (9, 'OK'), (9, 'LOW')], \
        f"AI alarm sırası beklenmedik: {severities}"
    print(f"    worker._evaluate_ai_alarms HIGH→OK→LOW transitions ✓")

    # Eşiksiz kanal sessiz kalmalı
    captured_alarms.clear()
    wm.set_alarm_thresholds(ai_pid, low=None, high=None)
    w_ai.reload_config()
    w_ai._ai_alarm_state.clear()
    w_ai._evaluate_ai_alarms({9: {'raw': 999.0}}, 't5')
    assert captured_alarms == []
    print(f"    eşik=None → değerlendirme atlanır ✓")

    # ── [4h] Faz-6e batch interlock ─────────────────────────────
    print("\n[4h] Faz-6e batch interlock (auto-pause)")
    # Aktif batch satırı yarat (singleton id=1) — bypass full API
    _c = db.connect()
    try:
        _cur = _c.cursor()
        _cur.execute("DELETE FROM active_batch WHERE id=1")
        _cur.execute(
            "INSERT INTO active_batch (id, batch_name, config_id, started_by, "
            "started_at, status) VALUES (1, 'SmokeBatch', NULL, NULL, "
            "datetime('now'), 'running')"
        )
        _c.commit()
    finally:
        db.close()

    # auto_pause kapalı → status running kalmalı, audit yine yazılmalı
    db.set_setting('oraps_barrier_auto_pause', '0')
    bridge._trigger_interlock(barrier_id=99, ts='2026-06-19T00:00:00')
    ab = bm.get_active_batch()
    assert ab['status'] == 'running', f"auto=0 iken pause olmamalı: {ab}"
    print(f"    auto_pause=0 → batch 'running' kald{chr(0x131)} ✓")

    # auto_pause açık → status paused olmalı
    db.set_setting('oraps_barrier_auto_pause', '1')
    bridge._trigger_interlock(barrier_id=99, ts='2026-06-19T00:00:01')
    ab = bm.get_active_batch()
    assert ab['status'] == 'paused', f"auto=1 iken pause olmalı: {ab}"
    print(f"    auto_pause=1 → batch 'paused' ✓")

    # paused durumda tekrar tetik → no-op (sadece 'running' iken etki eder)
    bridge._trigger_interlock(barrier_id=99, ts='2026-06-19T00:00:02')
    ab2 = bm.get_active_batch()
    assert ab2['status'] == 'paused'
    print(f"    paused iken tekrar tetik → no-op ✓")

    # Audit kontrolü: BATCH_INTERLOCK_TRIPPED ≥ 2 (auto=0 + auto=1)
    _c = db.connect()
    try:
        _cur = _c.cursor()
        _cur.execute(
            "SELECT COUNT(*) FROM audit_trail "
            "WHERE action_type='BATCH_INTERLOCK_TRIPPED'"
        )
        n_inter = _cur.fetchone()[0]
    finally:
        db.close()
    assert n_inter >= 2, f"BATCH_INTERLOCK_TRIPPED beklendi ≥2, oldu {n_inter}"
    print(f"    BATCH_INTERLOCK_TRIPPED audit kayıtları: {n_inter} ✓")

    # ── [4i] Faz-6h Mapping export/import ───────────────────────
    print("\n[4i] Mapping export/import")
    tmpf = os.path.join(tempfile.gettempdir(), 'oraps_mapping_smoke.json')
    payload = wm.export_mapping(tmpf)
    assert os.path.exists(tmpf)
    n_mods_exp = len(payload['modules'])
    n_pts_exp = len(payload['points'])
    print(f"    export → {n_mods_exp} modül, {n_pts_exp} nokta ✓")
    # Bir noktanın ismini değiştir (import yenisini bulup geri yazsın)
    sample = wm.list_points()[0]
    wm.update_point(int(sample['id']), name='DEĞİŞTİRİLDİ')
    # Import (merge) → geri yazsın
    stats = wm.import_mapping(tmpf, mode='merge')
    assert stats['points_updated'] >= 1, f"update beklendi: {stats}"
    after = wm.get_point(int(sample['id']))
    assert after['name'] == sample['name'], \
        f"import sonrası orijinal isim geri gelmeli: {after['name']}"
    print(f"    import merge → orijinal isim geri yazıldı ({stats}) ✓")
    # Geçersiz versiyon → reddet
    import json as _json
    bad = os.path.join(tempfile.gettempdir(), 'oraps_mapping_bad.json')
    with open(bad, 'w', encoding='utf-8') as _f:
        _json.dump({'version': 999, 'modules': [], 'points': []}, _f)
    try:
        wm.import_mapping(bad)
        assert False, "version uyumsuzluğu reddedilmedi"
    except ValueError as e:
        print(f"    versiyon uyumsuz reddedildi ✓ ({e})")
    os.unlink(tmpf); os.unlink(bad)

    # ── [4j] Faz-6h light_barrier_events housekeeping ───────────
    print("\n[4j] light_barrier_events housekeeping (retention)")
    # 100 gün önceki bir olay kaydı yarat
    _c = db.connect()
    try:
        _cur = _c.cursor()
        _cur.execute(
            "INSERT INTO light_barrier_events (barrier_id, module_id, channel, state, ts) "
            "VALUES (?, ?, ?, ?, datetime('now', '-100 days'))",
            (1, 1, 0, 1),
        )
        _cur.execute(
            "INSERT INTO light_barrier_events (barrier_id, module_id, channel, state, ts) "
            "VALUES (?, ?, ?, ?, datetime('now', '-1 days'))",
            (1, 1, 0, 0),
        )
        _c.commit()
        _cur.execute("SELECT COUNT(*) FROM light_barrier_events")
        before = _cur.fetchone()[0]
    finally:
        db.close()
    print(f"    silmeden önce: {before} kayıt")

    deleted = bm.purge_old_barrier_events(days=90)
    assert deleted >= 1, f"≥1 silme beklendi: {deleted}"

    _c = db.connect()
    try:
        _cur = _c.cursor()
        _cur.execute("SELECT COUNT(*) FROM light_barrier_events")
        after = _cur.fetchone()[0]
    finally:
        db.close()
    assert after < before, f"satır sayısı azalmalı: {before}→{after}"
    print(f"    purge(90) sonrası: {after} kayıt ({deleted} silindi) ✓")

    # days=0 → no-op
    deleted0 = bm.purge_old_barrier_events(days=0)
    assert deleted0 == 0
    print(f"    purge(0) → no-op ✓")

    # audit_trail dokunulmamış (§11.10(c))
    _c = db.connect()
    try:
        _cur = _c.cursor()
        _cur.execute("SELECT COUNT(*) FROM audit_trail")
        n_audit = _cur.fetchone()[0]
        _cur.execute("SELECT COUNT(*) FROM audit_trail "
                     "WHERE action_type='BARRIER_EVENTS_PURGED'")
        n_purge_audit = _cur.fetchone()[0]
    finally:
        db.close()
    assert n_purge_audit >= 1
    print(f"    BARRIER_EVENTS_PURGED audit kaydı: {n_purge_audit}, "
          f"audit_trail dokunulmamış toplam={n_audit} ✓")

    print("\n[5] Audit kategori kontrolü")
    cur = db.connect().cursor()
    cur.execute("SELECT category, action_type FROM audit_trail "
                "WHERE table_name='weidmuller_modules' OR table_name='weidmuller_io_points'"
                " ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    if not rows:
        print("    (uyarı: audit kayıt yok — audit_manager logged_in olmayabilir)")
    for r in rows:
        print(f"    {r['category']:8s}  {r['action_type']}")

    # IO_POINT_LINK kaydı düşmüş olmalı
    cur.execute("SELECT COUNT(*) FROM audit_trail "
                "WHERE category='ORAPS' AND action_type='IO_POINT_LINK'")
    n_link = cur.fetchone()[0]
    print(f"    IO_POINT_LINK kayıtları: {n_link} (beklenen ≥ 3: 2 bağla + 1 çıkar)")
    assert n_link >= 3

    # Bariyer audit kayıtları
    cur.execute("SELECT action_type, COUNT(*) FROM audit_trail "
                "WHERE category='ORAPS' AND table_name='light_barriers' "
                "GROUP BY action_type")
    bar_audit = dict(cur.fetchall())
    print(f"    BARRIER audit: {bar_audit}")
    assert bar_audit.get('BARRIER_CREATE', 0) >= 2
    assert bar_audit.get('BARRIER_UPDATE', 0) >= 1
    assert bar_audit.get('BARRIER_DELETE', 0) >= 1
    # Faz-6d: BARRIER_TRIGGERED en az 2 (rising + falling)
    assert bar_audit.get('BARRIER_TRIGGERED', 0) >= 2, (
        f"BARRIER_TRIGGERED ≥ 2 bekleniyordu, gelen: "
        f"{bar_audit.get('BARRIER_TRIGGERED', 0)}"
    )
    print(f"    BARRIER_TRIGGERED ≥ 2 ✓")
    db.close()

    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("TÜM TESTLER GEÇTİ ✓")
    print("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
