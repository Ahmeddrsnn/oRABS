"""Weidmüller seed + v3 migration doğrulama.

1) Fresh DB → modül haritası 32DI+16DO (ai/ao=0, di_words=2, input=32),
   48 nokta (S1_/S2_/S3_), IP=192.168.0.222, versiyon=3.
2) Eski fabrika-default DB (v2, ai_words=4, 40 nokta) → migration sonrası
   fresh ile aynı harita; AI/AO silinir, 16 yeni DI eklenir, adlar S*.
3) Elle yapılandırılmış (link'li) modül → migration DOKUNMAZ.

Komut: python _verify_weidmuller_seed.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

EXPECT_MAP = {'input_count': 32, 'di_words': 2, 'ai_words': 0,
              'ao_words': 0, 'do_words': 1, 'output_count': 16,
              'output_start': 0x0800, 'input_start': 0x0000}


def _check_map(row, label):
    for k, v in EXPECT_MAP.items():
        assert row[k] == v, f"{label}: {k}={row[k]} beklenen {v}"
    print(f"    {label}: register haritası OK ({dict(EXPECT_MAP)})")


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def scenario_fresh():
    print("\n[1] Fresh DB seed")
    db_path = tempfile.mktemp(suffix='.db')
    from core.database import Database
    Database(db_path)
    conn = _open(db_path)
    cur = conn.cursor()

    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='oraps_weidmuller_ip'")
    ip = cur.fetchone()[0]
    assert ip == '192.168.0.222', f"IP seed yanlış: {ip}"
    print(f"    oraps_weidmuller_ip = {ip} OK")

    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='weidmuller_schema_version'")
    ver = cur.fetchone()[0]
    assert ver == '3', f"versiyon {ver} != 3"
    print(f"    weidmuller_schema_version = {ver} OK")

    cur.execute('SELECT * FROM weidmuller_modules')
    mods = cur.fetchall()
    assert len(mods) == 1
    assert mods[0]['host'] == '192.168.0.222'
    _check_map(mods[0], 'modül')

    cur.execute('SELECT point_type, COUNT(*) n FROM weidmuller_io_points GROUP BY point_type')
    dist = {r['point_type']: r['n'] for r in cur.fetchall()}
    assert dist == {'DI': 32, 'DO': 16}, f"nokta dağılımı: {dist}"
    print(f"    nokta dağılımı {dist} OK")

    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=0")
    assert cur.fetchone()[0] == 'S1_DI1'
    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=16")
    assert cur.fetchone()[0] == 'S2_DI1'
    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=31")
    assert cur.fetchone()[0] == 'S2_DI16'
    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DO' AND channel=15")
    assert cur.fetchone()[0] == 'S3_DO16'
    print("    adlandırma S1_/S2_/S3_ OK")

    # link seed edilmemeli (kullanıcı kararı: sadece bağlantı/okuma ayarları)
    cur.execute('SELECT COUNT(*) FROM weidmuller_io_points WHERE link_type IS NOT NULL')
    assert cur.fetchone()[0] == 0, "fresh DB'de link olmamalı"
    print("    link yok (beklenen) OK")
    conn.close()
    os.remove(db_path)


def _make_legacy_db(db_path, with_link=False):
    """Yeni PC'deki gibi eski fabrika-default DB üret: önce güncel şema ile
    aç, sonra modülü ESKİ haritaya geri boz + AI/AO noktalarını geri ekle +
    versiyonu 2'ye indir."""
    from core.database import Database
    Database(db_path)
    conn = _open(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE weidmuller_modules SET input_count=16, di_words=1, "
                "ai_words=4, ao_words=4, host='192.168.1.100', "
                "description='Weidmüller UR20-FBC-MOD-TCP (varsayılan modül)'")
    cur.execute('SELECT id FROM weidmuller_modules')
    mid = cur.fetchone()[0]
    # Eski seed görünümü: DI/DO adları fabrika kalıbı, 16..31 DI yok, AI/AO var
    cur.execute("DELETE FROM weidmuller_io_points WHERE point_type='DI' AND channel>=16")
    for ch in range(16):
        cur.execute("UPDATE weidmuller_io_points SET name=? WHERE module_id=? AND point_type='DI' AND channel=?",
                    (f'DI{ch+1}', mid, ch))
        cur.execute("UPDATE weidmuller_io_points SET name=? WHERE module_id=? AND point_type='DO' AND channel=?",
                    (f'DO{ch+1}', mid, ch))
    for ch in range(4):
        cur.execute("INSERT INTO weidmuller_io_points (module_id, point_type, channel, name, unit, scale, offset, is_visible, sort_order, description) VALUES (?, 'AI', ?, ?, '%', 1.0, 0.0, 1, ?, '')",
                    (mid, ch, f'AI{ch+1}', 300 + ch))
        cur.execute("INSERT INTO weidmuller_io_points (module_id, point_type, channel, name, unit, scale, offset, is_visible, sort_order, description) VALUES (?, 'AO', ?, ?, '%', 1.0, 0.0, 1, ?, '')",
                    (mid, ch, f'AO{ch+1}', 400 + ch))
    if with_link:
        cur.execute("UPDATE weidmuller_io_points SET link_type='door', link_id=1 "
                    "WHERE module_id=? AND point_type='DI' AND channel=0", (mid,))
    cur.execute("UPDATE system_settings SET setting_value='2' WHERE setting_key='weidmuller_schema_version'")
    conn.commit()
    conn.close()
    return mid


def scenario_migration():
    print("\n[2] v2→v3 migration (dokunulmamış fabrika DB)")
    db_path = tempfile.mktemp(suffix='.db')
    _make_legacy_db(db_path)
    from core.database import Database
    Database(db_path)  # yeniden aç → migration çalışır
    conn = _open(db_path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM weidmuller_modules')
    _check_map(cur.fetchone(), 'migrate edilen modül')
    cur.execute('SELECT point_type, COUNT(*) n FROM weidmuller_io_points GROUP BY point_type')
    dist = {r['point_type']: r['n'] for r in cur.fetchall()}
    assert dist == {'DI': 32, 'DO': 16}, f"nokta dağılımı: {dist}"
    print(f"    AI/AO silindi, DI 16..31 eklendi: {dist} OK")
    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=0")
    assert cur.fetchone()[0] == 'S1_DI1', "fabrika adı S1_'e çevrilmeli"
    cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=20")
    assert cur.fetchone()[0] == 'S2_DI5'
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='weidmuller_schema_version'")
    assert cur.fetchone()[0] == '3'
    print("    adlar + versiyon=3 OK")
    conn.close()
    os.remove(db_path)


def scenario_configured_untouched():
    print("\n[3] Elle yapılandırılmış (link'li) modül korunur")
    db_path = tempfile.mktemp(suffix='.db')
    _make_legacy_db(db_path, with_link=True)
    from core.database import Database
    Database(db_path)
    conn = _open(db_path)
    cur = conn.cursor()
    cur.execute('SELECT ai_words, di_words, input_count FROM weidmuller_modules')
    row = cur.fetchone()
    assert (row['ai_words'], row['di_words'], row['input_count']) == (4, 1, 16), \
        "link'li modül migrate edilmemeliydi"
    cur.execute("SELECT COUNT(*) FROM weidmuller_io_points WHERE point_type='AI'")
    assert cur.fetchone()[0] == 4, "AI noktaları korunmalıydı"
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='weidmuller_schema_version'")
    assert cur.fetchone()[0] == '3', "versiyon yine de 3 olmalı"
    print("    modül + noktalar aynen duruyor, versiyon=3 OK")
    conn.close()
    os.remove(db_path)


if __name__ == '__main__':
    print("=" * 60)
    print("Weidmüller seed + v3 migration doğrulama")
    print("=" * 60)
    scenario_fresh()
    scenario_migration()
    scenario_configured_untouched()
    print("\nTÜM SENARYOLAR GEÇTİ ✓")
