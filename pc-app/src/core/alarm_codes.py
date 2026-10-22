"""Merkezi alarm kodu kataloğu (Faz-13).

Sistemdeki tüm alarm/olay tiplerine standart kod atar (kullanıcı onaylı liste,
2026-08-01). Kodlar audit açıklamalarının başına `[KP-01]` biçiminde eklenir
(bkz. `core.audit.AuditManager.log_action`), Son Olaylar listesi, alarm banner
ve batch PDF raporlarında görünür.

Gruplar:
  KP = Kapı            MS = Makine Durdurma   IB = Işık Bariyeri
  AS = Acil Stop       PT = Port              LF = LAF Ünitesi
  AI = Analog Giriş    BT = Batch

Excel çıktısı: `_gen_alarm_codes_xlsx.py` bu kataloğu tek kaynak olarak
kullanır — listeyi değiştirirken YALNIZCA burayı güncelleyin.
"""

from __future__ import annotations

from typing import Optional, Tuple

# action_type → (kod, Türkçe açıklama, severity: 'crit'|'warn'|'info')
ALARM_CODES: dict[str, Tuple[str, str, str]] = {
    # ── KP: Kapı ─────────────────────────────────────────────────
    'DOOR_OPENED':             ('KP-01', 'Kapı açıldı', 'info'),
    'DOOR_CLOSED':             ('KP-02', 'Kapı kapatıldı', 'info'),
    'DOOR_FORCED':             ('KP-03', 'Kilitli kapı açıldı (zorlandı)', 'crit'),
    'DOOR_FORCED_CLOSED':      ('KP-04', 'Kilitli kapı kapatıldı', 'warn'),
    # ── MS: Makine Durdurma ──────────────────────────────────────
    # MS-01 varsayılan; GLT aşaması (MS-03) ve batch-dışı kilit (MS-04)
    # varyantlarının kodu emisyon noktasında (weidmuller_bridge) açıkça
    # description'a yazılır — log_action '[' ile başlayan açıklamaya
    # tekrar kod eklemez.
    'MACHINE_STOP_TRIGGERED':  ('MS-01', 'Makine durduran kapı açıldı (röle DUR)', 'crit'),
    'MACHINE_STOP_CLEARED':    ('MS-02', 'Makine durdurma temizlendi', 'info'),
    # ── IB: Işık Bariyeri ────────────────────────────────────────
    'BARRIER_TRIGGERED':       ('IB-01', 'Işık bariyeri tetiklendi', 'crit'),
    'BATCH_INTERLOCK_TRIPPED': ('IB-02', 'Bariyer interlock — otomatik duraklatma', 'crit'),
    # ── AS: Acil Stop ────────────────────────────────────────────
    'ESTOP_TRIGGERED':         ('AS-01', 'ACİL STOP BASILDI', 'crit'),
    'ESTOP_RELEASED':          ('AS-02', 'Acil stop serbest bırakıldı', 'info'),
    # ── PT: Port ─────────────────────────────────────────────────
    'PORT_MOTION':             ('PT-01', 'Port hareketi algılandı', 'info'),
    'PORT_MOTION_END':         ('PT-02', 'Port hareketi sona erdi', 'info'),
    # Kablosuz IR bariyer sensörleri portlara bağlı çalışır → kullanıcı
    # kararıyla PT grubunda (2026-08-01).
    'BARRIER_LOW_BATTERY':     ('PT-03', 'Kablosuz bariyer sensörü pili düşük', 'warn'),
    'BARRIER_DISCOVERED':      ('PT-04', 'Yeni kablosuz bariyer sensörü keşfedildi', 'info'),
    # ── LF: LAF Ünitesi ──────────────────────────────────────────
    'LAF_ALARM':               ('LF-01', 'LAF cihaz alarmı', 'crit'),
    'LAF_ALARM_CLEAR':         ('LF-02', 'LAF alarmı temizlendi', 'info'),
    # Legacy takma adlar (eski whitelist referansları):
    'LAF_ALARM_RAISED':        ('LF-01', 'LAF cihaz alarmı', 'crit'),
    'LAF_ALARM_CLEARED':       ('LF-02', 'LAF alarmı temizlendi', 'info'),
    # ── AI: Analog Giriş ─────────────────────────────────────────
    'AI_ALARM_HIGH':           ('AI-01', 'Analog giriş yüksek eşik aşıldı', 'crit'),
    'AI_ALARM_LOW':            ('AI-02', 'Analog giriş düşük eşik aşıldı', 'crit'),
    'AI_ALARM_OK':             ('AI-03', 'Analog giriş normale döndü', 'info'),
    # ── BT: Batch ────────────────────────────────────────────────
    'BATCH_PAUSED':            ('BT-01', 'Batch duraklatıldı', 'warn'),
    'BATCH_RESUMED':           ('BT-02', 'Batch devam etti', 'info'),
}

# Emisyon noktasında açıkça kullanılan varyant kodları (action_type'ı
# MACHINE_STOP_TRIGGERED olan ama bağlamı farklı olan durumlar).
VARIANT_CODES: dict[str, Tuple[str, str, str]] = {
    'MS-03': ('MS-03', 'GLT aşaması kilidi (aşama bitene kadar makine DUR)', 'warn'),
    'MS-04': ('MS-04', 'Batch dışı kilit (ORABS hariç her zaman durdur ayarı)', 'warn'),
}


def code_for(action_type: str) -> Optional[str]:
    """action_type için alarm kodu ('KP-01') veya None."""
    entry = ALARM_CODES.get((action_type or '').strip().upper())
    return entry[0] if entry else None


def label_for(action_type: str) -> Optional[str]:
    entry = ALARM_CODES.get((action_type or '').strip().upper())
    return entry[1] if entry else None


def prefix_description(action_type: str, description: str) -> str:
    """Açıklamanın başına `[KOD] ` ekle.

    Kurallar:
      - action_type katalogda yoksa açıklama aynen döner.
      - Açıklama zaten '[' ile başlıyorsa (emisyon noktası özel kod yazmış,
        örn. '[MS-03] ...') dokunulmaz — çift kod eklenmez.
    """
    desc = description or ''
    code = code_for(action_type)
    if not code or desc.lstrip().startswith('['):
        return desc
    return f"[{code}] {desc}"


def all_rows() -> list:
    """Excel/rapor üretimi için tam liste (varyantlar dahil).
    Return: [(kod, açıklama, severity, action_type), ...] kod sıralı."""
    rows = []
    seen_codes = set()
    for action, (code, label, sev) in ALARM_CODES.items():
        if code in seen_codes:
            continue   # legacy alias'ları tekrar etme
        seen_codes.add(code)
        rows.append((code, label, sev, action))
    for code, (c, label, sev) in VARIANT_CODES.items():
        rows.append((c, label, sev, 'MACHINE_STOP_TRIGGERED (varyant)'))
    rows.sort(key=lambda r: (r[0].split('-')[0], int(r[0].split('-')[1])))
    return rows
