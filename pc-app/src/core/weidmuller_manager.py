"""
Weidmüller IO Manager (Faz-6a)
==============================
Thin domain layer on top of `core.database.Database` for the ORAPS
Weidmüller IO panel:
  - Modül CRUD (`weidmuller_modules`)        — admin-only mutations
  - IO point CRUD (`weidmuller_io_points`)   — admin-only mutations
  - Salt-okuma sorgular (panel ve worker için)

All DB calls go through the shared Database (RLock-protected). This module
never opens its own sqlite cursor.

Audit policy (21 CFR Part 11)
- Mutations → audit.log_action(category='ORAPS').
- DO/AO yazma olayları worker tarafından IO_WRITE olarak audit edilir
  (bu modülde değil — worker emits, GUI thread logs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
import json
import os


VALID_POINT_TYPES = ('DI', 'DO', 'AI', 'AO')
VALID_LINK_TYPES = ('door', 'door_group', 'port', 'laf', 'barrier', 'estop',
                    'buzzer')


class PermissionDenied(Exception):
    """Raised when a non-admin attempts an admin-only mutation."""


class WeidmullerManager:
    """Domain operations for Weidmüller IO modules and points."""

    def __init__(self, database, auth_manager, audit_manager=None):
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager

    # ── Helpers ──────────────────────────────────────────────────
    def _is_admin(self) -> bool:
        return self.auth.get_current_user_role() == 'Admin'

    def _audit(self, action_type: str, description: str,
               record_id: Optional[int] = None,
               old_value: str = '', new_value: str = '',
               table_name: str = 'weidmuller_modules',
               field_name: Optional[str] = None):
        if not self.audit:
            return
        try:
            self.audit.log_action(
                action_type=action_type,
                table_name=table_name,
                record_id=record_id,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                description=description,
                category='ORAPS',
            )
        except Exception:
            import traceback
            traceback.print_exc()

    # ── Modules ──────────────────────────────────────────────────
    def list_modules(self, only_active: bool = False) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, name, host, port, unit_id, timeout_sec, '
                   'output_start, output_count, input_start, input_count, '
                   'ao_words, do_words, ai_words, di_words, raw_max, '
                   'poll_ms, is_active, mock_mode, description, created_at '
                   'FROM weidmuller_modules')
            if only_active:
                sql += ' WHERE is_active=1'
            sql += ' ORDER BY id'
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def get_module(self, module_id: int) -> Optional[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM weidmuller_modules WHERE id=?', (module_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            self.db.close()

    def add_module(self, name: str, host: str, port: int = 502,
                   unit_id: int = 255, mock_mode: int = 0,
                   description: str = '', **kwargs) -> int:
        if not self._is_admin():
            raise PermissionDenied("Sadece admin modül ekleyebilir.")
        name = (name or '').strip()
        if not name:
            raise ValueError("Modül adı boş olamaz.")

        defaults = {
            'timeout_sec': 2.0,
            'output_start': 0x0800,
            'output_count': 16,
            'input_start':  0x0000,
            'input_count':  32,
            'ao_words': 0, 'do_words': 1, 'ai_words': 0, 'di_words': 2,
            'raw_max': 27648, 'poll_ms': 500, 'is_active': 1,
        }
        defaults.update(kwargs)

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO weidmuller_modules
                   (name, host, port, unit_id, timeout_sec,
                    output_start, output_count, input_start, input_count,
                    ao_words, do_words, ai_words, di_words, raw_max,
                    poll_ms, is_active, mock_mode, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, host, port, unit_id, defaults['timeout_sec'],
                 defaults['output_start'], defaults['output_count'],
                 defaults['input_start'], defaults['input_count'],
                 defaults['ao_words'], defaults['do_words'],
                 defaults['ai_words'], defaults['di_words'],
                 defaults['raw_max'], defaults['poll_ms'],
                 defaults['is_active'], int(bool(mock_mode)),
                 description, datetime.now().isoformat()),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        self._audit('IO_MODULE_ADD',
                    f"IO modülü eklendi: {name} ({host}:{port})",
                    record_id=new_id, new_value=name)
        return new_id

    def update_module(self, module_id: int, **fields):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin modül güncelleyebilir.")
        if not fields:
            return
        allowed = {'name', 'host', 'port', 'unit_id', 'timeout_sec',
                   'output_start', 'output_count', 'input_start', 'input_count',
                   'ao_words', 'do_words', 'ai_words', 'di_words', 'raw_max',
                   'poll_ms', 'is_active', 'mock_mode', 'description'}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Bilinmeyen alan(lar): {bad}")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM weidmuller_modules WHERE id=?', (module_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Modül bulunamadı: id={module_id}")
            old = dict(row)
            sets = ', '.join(f'{k}=?' for k in fields)
            params = list(fields.values()) + [module_id]
            cur.execute(f'UPDATE weidmuller_modules SET {sets} WHERE id=?', params)
            conn.commit()
        finally:
            self.db.close()

        changed = {k: (old.get(k), v) for k, v in fields.items() if old.get(k) != v}
        if changed:
            desc = f"IO modülü #{module_id} güncellendi: " + ', '.join(
                f"{k}: {a}→{b}" for k, (a, b) in changed.items()
            )
            self._audit('IO_MODULE_UPDATE', desc, record_id=module_id,
                        old_value=str({k: a for k, (a, _) in changed.items()}),
                        new_value=str({k: b for k, (_, b) in changed.items()}))

    def delete_module(self, module_id: int):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin modül silebilir.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT name FROM weidmuller_modules WHERE id=?', (module_id,))
            row = cur.fetchone()
            if not row:
                return
            name = row['name']
            cur.execute('DELETE FROM weidmuller_modules WHERE id=?', (module_id,))
            conn.commit()
        finally:
            self.db.close()
        self._audit('IO_MODULE_DELETE',
                    f"IO modülü silindi: {name} (id={module_id})",
                    record_id=module_id, old_value=name)

    # ── IO Points ────────────────────────────────────────────────
    def list_points(self, module_id: Optional[int] = None,
                    point_type: Optional[str] = None,
                    only_visible: bool = False) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, module_id, point_type, channel, name, unit, '
                   'scale, offset, is_visible, sort_order, description, '
                   'link_type, link_id, link_role, low_alarm, high_alarm '
                   'FROM weidmuller_io_points')
            where, params = [], []
            if module_id is not None:
                where.append('module_id=?'); params.append(module_id)
            if point_type:
                where.append('point_type=?'); params.append(point_type)
            if only_visible:
                where.append('is_visible=1')
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY sort_order, channel, id'
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def get_point(self, point_id: int) -> Optional[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM weidmuller_io_points WHERE id=?', (point_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            self.db.close()

    def add_point(self, module_id: int, point_type: str, channel: int,
                  name: str, unit: str = '', scale: float = 1.0,
                  offset: float = 0.0, is_visible: int = 1,
                  sort_order: int = 0, description: str = '') -> int:
        if not self._is_admin():
            raise PermissionDenied("Sadece admin IO noktası ekleyebilir.")
        if point_type not in VALID_POINT_TYPES:
            raise ValueError(f"point_type {VALID_POINT_TYPES} olmalı.")
        name = (name or '').strip()
        if not name:
            raise ValueError("İsim boş olamaz.")
        if channel < 0:
            raise ValueError("channel ≥ 0 olmalı.")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO weidmuller_io_points
                   (module_id, point_type, channel, name, unit, scale, offset,
                    is_visible, sort_order, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (module_id, point_type, channel, name, unit, scale, offset,
                 int(bool(is_visible)), sort_order, description),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        self._audit('IO_POINT_ADD',
                    f"IO noktası eklendi: {point_type}{channel} '{name}' (modül {module_id})",
                    record_id=new_id, table_name='weidmuller_io_points',
                    new_value=name)
        return new_id

    def update_point(self, point_id: int, **fields):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin IO noktası güncelleyebilir.")
        if not fields:
            return
        allowed = {'name', 'unit', 'scale', 'offset', 'is_visible',
                   'sort_order', 'description', 'channel', 'point_type',
                   'link_type', 'link_id', 'link_role',
                   'low_alarm', 'high_alarm'}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Bilinmeyen alan(lar): {bad}")
        if 'point_type' in fields and fields['point_type'] not in VALID_POINT_TYPES:
            raise ValueError("point_type geçersiz.")
        if 'link_type' in fields and fields['link_type'] is not None \
                and fields['link_type'] not in VALID_LINK_TYPES:
            raise ValueError(f"link_type {VALID_LINK_TYPES} ya da None olmalı.")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM weidmuller_io_points WHERE id=?', (point_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"IO noktası bulunamadı: id={point_id}")
            old = dict(row)
            sets = ', '.join(f'{k}=?' for k in fields)
            params = list(fields.values()) + [point_id]
            cur.execute(f'UPDATE weidmuller_io_points SET {sets} WHERE id=?', params)
            conn.commit()
        finally:
            self.db.close()

        changed = {k: (old.get(k), v) for k, v in fields.items() if old.get(k) != v}
        if changed:
            desc = f"IO noktası #{point_id} güncellendi: " + ', '.join(
                f"{k}: {a}→{b}" for k, (a, b) in changed.items()
            )
            self._audit('IO_POINT_UPDATE', desc, record_id=point_id,
                        table_name='weidmuller_io_points',
                        old_value=str({k: a for k, (a, _) in changed.items()}),
                        new_value=str({k: b for k, (_, b) in changed.items()}))

    def delete_point(self, point_id: int):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin IO noktası silebilir.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT name, point_type, channel FROM weidmuller_io_points WHERE id=?',
                        (point_id,))
            row = cur.fetchone()
            if not row:
                return
            label = f"{row['point_type']}{row['channel']} '{row['name']}'"
            cur.execute('DELETE FROM weidmuller_io_points WHERE id=?', (point_id,))
            conn.commit()
        finally:
            self.db.close()
        self._audit('IO_POINT_DELETE',
                    f"IO noktası silindi: {label} (id={point_id})",
                    record_id=point_id, table_name='weidmuller_io_points',
                    old_value=label)

    # ── Audit hook for worker writes ─────────────────────────────
    def log_write(self, module_id: int, point_type: str, channel: int,
                  value, success: bool, error_msg: str = ''):
        """Called by GUI thread when worker reports a DO/AO write attempt.

        IO seviyesindeki tekil yazma komutları audit trail'e YAZILMAZ.
        Kullanıcı için anlamlı olan üst seviye event'ler (BATCH_STARTED,
        BATCH_DOOR_UNLOCK, ESTOP_TRIGGERED vs.) kendi kaynaklarında zaten
        loglanıyor. DO/AO yazma detayları audit'i gereksiz şişirir.
        """
        pass

    # ── Linking (IO point ↔ door/port/laf) ───────────────────────
    def set_link(self, point_id: int, link_type: Optional[str],
                 link_id: Optional[int], link_role: str = ''):
        """Bir IO noktasını kapıya/porta/LAF sensörüne bağlar.

        `link_type=None` → bağlantıyı temizler.
        FK kullanmıyoruz (hedef silinirse `resolve_link_label` 'silinmiş' der).
        """
        if not self._is_admin():
            raise PermissionDenied("Sadece admin IO bağlantısı kurabilir.")
        if link_type is not None and link_type not in VALID_LINK_TYPES:
            raise ValueError(f"link_type {VALID_LINK_TYPES} ya da None olmalı.")
        if link_type is not None and link_id is None:
            raise ValueError("link_type verildiyse link_id gerekli.")
        if link_type is None:
            link_id = None
            link_role = ''

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT point_type, channel, name, link_type, link_id, link_role '
                        'FROM weidmuller_io_points WHERE id=?', (point_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"IO noktası bulunamadı: id={point_id}")
            old = dict(row)
            cur.execute(
                'UPDATE weidmuller_io_points '
                'SET link_type=?, link_id=?, link_role=? WHERE id=?',
                (link_type, link_id, link_role or '', point_id),
            )
            conn.commit()
        finally:
            self.db.close()

        label = f"{old['point_type']}{old['channel']} '{old['name']}'"
        if link_type:
            target = self.resolve_link_label(link_type, link_id)
            desc = f"IO bağlandı: {label} → {link_type}:{link_id} ({target})"
            if link_role:
                desc += f" rol={link_role}"
        else:
            old_label = self.resolve_link_label(old['link_type'], old['link_id']) \
                if old['link_type'] else ''
            desc = f"IO bağlantısı kaldırıldı: {label}" + (
                f" (önceki: {old['link_type']}:{old['link_id']} {old_label})"
                if old['link_type'] else ''
            )
        self._audit('IO_POINT_LINK', desc, record_id=point_id,
                    table_name='weidmuller_io_points',
                    old_value=f"{old['link_type']}:{old['link_id']}",
                    new_value=f"{link_type}:{link_id}")

    # ── AI alarm eşikleri (Faz-6g) ───────────────────────────────
    def set_alarm_thresholds(self, point_id: int,
                             low: Optional[float] = None,
                             high: Optional[float] = None):
        """AI noktasında low/high alarm eşiklerini ayarla. None değerler
        ilgili eşiği devre dışı bırakır. Mühendislik biriminde girilir
        (scale*raw+offset sonrası). Sadece point_type='AI' için anlamlı
        ama burada zorlanmaz — DI/DO için NULL bırakılır."""
        if not self._is_admin():
            raise PermissionDenied("Sadece admin alarm eşiği değiştirebilir.")
        if low is not None and high is not None and float(low) >= float(high):
            raise ValueError("low_alarm < high_alarm olmalı.")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT point_type, channel, name, low_alarm, high_alarm '
                        'FROM weidmuller_io_points WHERE id=?', (point_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"IO noktası bulunamadı: id={point_id}")
            old = dict(row)
            lo = None if low is None else float(low)
            hi = None if high is None else float(high)
            cur.execute(
                'UPDATE weidmuller_io_points SET low_alarm=?, high_alarm=? WHERE id=?',
                (lo, hi, point_id),
            )
            conn.commit()
        finally:
            self.db.close()

        label = f"{old['point_type']}{old['channel']} '{old['name']}'"
        desc = (f"Alarm eşikleri güncellendi: {label} "
                f"low={old['low_alarm']}→{lo} high={old['high_alarm']}→{hi}")
        self._audit('IO_POINT_ALARM_SET', desc, record_id=point_id,
                    table_name='weidmuller_io_points',
                    old_value=f"low={old['low_alarm']},high={old['high_alarm']}",
                    new_value=f"low={lo},high={hi}")

    def list_unlinked(self, module_id: Optional[int] = None) -> List[Dict]:
        """Henüz bir hedefe bağlanmamış (link_type IS NULL) IO noktaları."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, module_id, point_type, channel, name '
                   'FROM weidmuller_io_points WHERE link_type IS NULL')
            params: List = []
            if module_id is not None:
                sql += ' AND module_id=?'
                params.append(module_id)
            sql += ' ORDER BY module_id, sort_order, channel'
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def list_links_for(self, link_type: str, link_id: int) -> List[Dict]:
        """Bir hedefe (kapı/port/LAF) bağlı tüm IO noktaları."""
        if link_type not in VALID_LINK_TYPES:
            return []
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, module_id, point_type, channel, name, link_role '
                'FROM weidmuller_io_points WHERE link_type=? AND link_id=? '
                'ORDER BY module_id, sort_order, channel',
                (link_type, link_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def resolve_link_label(self, link_type: Optional[str],
                           link_id: Optional[int]) -> str:
        """Bağlantının insanca okunabilir özeti. Hedef silinmişse '(silinmiş)'."""
        if not link_type or link_id is None:
            return ''
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            if link_type == 'door':
                cur.execute(
                    'SELECT door_index, label FROM oraps_door_labels '
                    'WHERE door_index=?', (link_id,)
                )
                r = cur.fetchone()
                if not r:
                    return f'Kapı #{link_id} (etiketsiz)'
                lbl = (r['label'] or '').strip()
                return f"Kapı {r['door_index']}" + (f" — {lbl}" if lbl else '')
            if link_type == 'port':
                cur.execute(
                    'SELECT port_index, label FROM oraps_port_labels '
                    'WHERE port_index=?', (link_id,)
                )
                r = cur.fetchone()
                if not r:
                    return f'Port #{link_id} (etiketsiz)'
                lbl = (r['label'] or '').strip()
                return f"Port {r['port_index']}" + (f" — {lbl}" if lbl else '')
            if link_type == 'laf':
                cur.execute('SELECT label FROM laf_sensors WHERE id=?', (link_id,))
                r = cur.fetchone()
                if not r:
                    return '(silinmiş sensör)'
                return f"LAF: {r['label']}"
            if link_type == 'barrier':
                cur.execute(
                    'SELECT label, door_a_index, door_b_index, door_indices '
                    'FROM light_barriers WHERE id=?', (link_id,)
                )
                r = cur.fetchone()
                if not r:
                    return f'(silinmiş bariyer #{link_id})'
                # door_indices JSON (yeni format) varsa onu kullan; yoksa a/b.
                _idxs = []
                try:
                    import json as _j
                    _raw = r['door_indices'] if 'door_indices' in r.keys() else ''
                    if _raw:
                        _v = _j.loads(_raw)
                        if isinstance(_v, list):
                            _idxs = [int(x) for x in _v]
                except Exception:
                    _idxs = []
                if not _idxs:
                    _idxs = sorted({int(r['door_a_index']), int(r['door_b_index'])})
                _idx_str = ', '.join(str(i) for i in _idxs)
                return f"Bariyer '{r['label']}' (Kapılar: {_idx_str})"
            if link_type == 'door_group':
                cur.execute(
                    'SELECT name, '
                    '       (SELECT COUNT(*) FROM oraps_door_labels '
                    '        WHERE group_id=g.id) AS n, '
                    '       (SELECT COUNT(*) FROM oraps_door_labels '
                    '        WHERE stop_group_id=g.id) AS ns '
                    'FROM oraps_door_groups g WHERE g.id=?', (link_id,)
                )
                r = cur.fetchone()
                if not r:
                    return f'(silinmiş kapı grubu #{link_id})'
                return (f"Kapı Grubu: {r['name']} "
                        f"(kilit: {r['n']} · durdurma: {r['ns']} kapı)")
            if link_type == 'estop':
                cur.execute(
                    'SELECT label FROM oraps_estop_buttons WHERE id=?',
                    (link_id,),
                )
                r = cur.fetchone()
                if not r:
                    return f'(silinmiş acil stop #{link_id})'
                return f"Acil Stop: {r['label']}"
            if link_type == 'buzzer':
                return "Buzzer (alarm kornası)"
        finally:
            self.db.close()
        return f"{link_type}:{link_id}"

    # ── Target listings (for IO link dialog) ─────────────────────
    def list_link_targets(self, link_type: str) -> List[Dict]:
        """Bağlanılabilir hedefleri döner. Her satır: {id, label, group}."""
        if link_type not in VALID_LINK_TYPES:
            return []
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            if link_type == 'door':
                # Veritabanındaki tüm kapıları getir (dinamik sayı)
                cur.execute(
                    'SELECT door_index, label FROM oraps_door_labels '
                    'WHERE is_visible=1 ORDER BY door_index'
                )
                rows = list(cur.fetchall())
                existing = {r['door_index']: (r['label'] or '').strip() for r in rows}
                max_door = max(existing.keys()) if existing else 12
                door_count = max(max_door, 12)
                out = []
                for i in range(1, door_count + 1):
                    lbl = existing.get(i, '')
                    # Sadece isimlendirilmiş kapıları veya ilk 12'yi göster
                    if i <= 12 or lbl:
                        out.append({
                            'id': i,
                            'label': f"Kapı {i}" + (f" — {lbl}" if lbl else ''),
                            'group': f'Kapılar (1..{door_count})',
                        })
                return out
            if link_type == 'port':
                cur.execute(
                    'SELECT port_index, label FROM oraps_port_labels '
                    'WHERE is_visible=1 ORDER BY port_index'
                )
                rows = list(cur.fetchall())
                existing = {r['port_index']: (r['label'] or '').strip() for r in rows}
                out = []
                for i in range(1, 15):
                    lbl = existing.get(i, '')
                    out.append({
                        'id': i,
                        'label': f"Port {i}" + (f" — {lbl}" if lbl else ''),
                        'group': 'Eldiven portları (1..14)',
                    })
                return out
            if link_type == 'laf':
                cur.execute(
                    'SELECT id, label, unit FROM laf_sensors '
                    'WHERE is_visible=1 ORDER BY sort_order, id'
                )
                return [{
                    'id': r['id'],
                    'label': f"{r['label']}" + (f" ({r['unit']})" if r['unit'] else ''),
                    'group': 'LAF sensörleri',
                } for r in cur.fetchall()]
            if link_type == 'barrier':
                cur.execute(
                    'SELECT id, label, door_a_index, door_b_index '
                    'FROM light_barriers WHERE is_active=1 '
                    'ORDER BY label'
                )
                return [{
                    'id': r['id'],
                    'label': (f"{r['label']} "
                              f"(Kapı {r['door_a_index']} ↔ Kapı {r['door_b_index']})"),
                    'group': 'Işık bariyerleri',
                } for r in cur.fetchall()]
            if link_type == 'door_group':
                cur.execute(
                    'SELECT g.id, g.name, '
                    '       (SELECT COUNT(*) FROM oraps_door_labels '
                    '        WHERE group_id=g.id) AS n, '
                    '       (SELECT COUNT(*) FROM oraps_door_labels '
                    '        WHERE stop_group_id=g.id) AS ns '
                    'FROM oraps_door_groups g ORDER BY g.name'
                )
                return [{
                    'id': r['id'],
                    'label': (f"{r['name']} "
                              f"(kilit: {r['n']} · durdurma: {r['ns']} kapı)"),
                    'group': 'Kapı grupları',
                } for r in cur.fetchall()]
            if link_type == 'estop':
                cur.execute(
                    'SELECT id, label FROM oraps_estop_buttons '
                    'WHERE is_enabled=1 ORDER BY id'
                )
                return [{
                    'id': r['id'],
                    'label': r['label'],
                    'group': 'Acil Stop butonları',
                } for r in cur.fetchall()]
            if link_type == 'buzzer':
                # Sanal hedef — buzzer kanal başına ayrı kayıt gerektirmez;
                # alarm banner'ı/acil stop yanınca rol='buzzer' DO'lar sürülür.
                return [{
                    'id': 0,
                    'label': 'Alarm kornası çıkışı (alarmda DO=1)',
                    'group': 'Buzzer',
                }]
        finally:
            self.db.close()
        return []

    # ── Live coupler probe (TCP, sync) ───────────────────────────
    def probe_coupler(self, module_id: int, timeout: float = 2.0) -> Dict:
        """TCP üzerinden coupler'a bağlanıp kimlik + işlem alanı boyutunu
        okur. UI'dan "🔍 Tara" butonu çağırır. Mock alanları:

        Dönüş:
            ok          : bool — bağlantı başarılı mı
            host/port   : str/int — denenen adres
            coupler_id  : str — ASCII kimlik (varsa)
            pi_words    : int — Process Input register sayısı (0 = okunamadı)
            po_words    : int — Process Output register sayısı (0 = okunamadı)
            di_est/do_est/ai_est/ao_est : int — kabaca tahmin
            error       : str — boşsa hata yok
        """
        mod = self.get_module(module_id)
        if not mod:
            return {'ok': False, 'error': 'Modül bulunamadı.'}

        host = mod['host']
        port = int(mod['port'])
        unit = int(mod.get('unit_id', 255))
        result = {
            'ok': False, 'host': host, 'port': port, 'unit_id': unit,
            'coupler_id': '', 'pi_words': 0, 'po_words': 0,
            'di_est': 0, 'do_est': 0, 'ai_est': 0, 'ao_est': 0,
            'error': '',
        }
        try:
            from pymodbus.client import ModbusTcpClient  # type: ignore
        except Exception as e:
            result['error'] = f"pymodbus import hatası: {e}"
            return result

        client = ModbusTcpClient(host=host, port=port, timeout=timeout)
        try:
            if not client.connect():
                result['error'] = f"Bağlanılamadı ({host}:{port})"
                return result

            # Coupler ID (8 reg, word-swap, low byte first)
            try:
                rr = client.read_holding_registers(address=0x1000, count=8, slave=unit)
                if not rr.isError():
                    swapped = bytearray()
                    for r in rr.registers:
                        swapped.append(r & 0xFF)
                        swapped.append((r >> 8) & 0xFF)
                    cid = swapped.decode('ascii', errors='replace')
                    result['coupler_id'] = cid.strip('\x00 ').strip()
            except Exception as e:
                result['error'] = f"Coupler ID okunamadı: {e}"

            # Process Input / Output sözcük sayıları (UR20 manual: 0x1010/0x1012)
            try:
                rr = client.read_holding_registers(address=0x1010, count=4, slave=unit)
                if not rr.isError() and len(rr.registers) >= 4:
                    # 32-bit big-endian: high reg first
                    result['pi_words'] = (rr.registers[0] << 16) | rr.registers[1]
                    result['po_words'] = (rr.registers[2] << 16) | rr.registers[3]
            except Exception:
                pass

            # Çok kaba tahmin: pi/po sözcüklerini DI/DO bit + AI/AO word'e böl
            # UR20'de tipik dizilim donanıma göre değişir; bu sadece bilgilendirme.
            pi = result['pi_words']
            po = result['po_words']
            # 1 word DI = 16 bit; ama analog da word kullanır → tahmini yok
            # Sadece toplam word sayısını rapor edelim
            result['di_est'] = pi * 16 if pi <= 2 else 0   # sadece dijital ise
            result['do_est'] = po * 16 if po <= 2 else 0
            result['ai_est'] = max(0, pi - 0)              # tahminde bulunma
            result['ao_est'] = max(0, po - 0)
            result['ok'] = True
        except Exception as e:
            result['error'] = f"Probe hatası: {e}"
        finally:
            try:
                client.close()
            except Exception:
                pass
        return result

    # ── Mapping export / import (Faz-6h) ─────────────────────────
    MAPPING_VERSION = 1

    def export_mapping(self, path: str) -> Dict:
        """Tüm IO modüllerini ve noktalarını (link & alarm dahil) JSON
        olarak yazar. Bariyer ve port-label gibi batch_manager alanları
        burada export edilmez — onlar ayrı audit kategorilerinde tutulur.
        Returns the in-memory dict that was written (for testability)."""
        if not self._is_admin():
            raise PermissionDenied("Sadece admin mapping export edebilir.")
        modules = self.list_modules()
        points = self.list_points()
        # module_id → name eşlemesi (taşınabilirlik için natural key)
        id_to_name = {int(m['id']): m['name'] for m in modules}
        export_points = []
        for p in points:
            mid = int(p['module_id'])
            d = dict(p)
            d.pop('id', None)
            d.pop('module_id', None)
            d['module_name'] = id_to_name.get(mid, '')
            export_points.append(d)
        payload = {
            'version': self.MAPPING_VERSION,
            'exported_at': datetime.now().isoformat(timespec='seconds'),
            'modules': [
                {k: m[k] for k in (
                    'name', 'host', 'port', 'unit_id', 'timeout_sec',
                    'output_start', 'output_count', 'input_start', 'input_count',
                    'ao_words', 'do_words', 'ai_words', 'di_words', 'raw_max',
                    'poll_ms', 'is_active', 'mock_mode', 'description')
                 if k in m}
                for m in modules
            ],
            'points': export_points,
        }
        # Atomik yazım
        path = os.fspath(path)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        self._audit(
            'IO_MAPPING_EXPORT',
            f"IO mapping export edildi → {path} "
            f"(modüller={len(payload['modules'])}, noktalar={len(payload['points'])})",
            table_name='weidmuller_modules',
        )
        return payload

    def import_mapping(self, path: str, mode: str = 'merge') -> Dict:
        """JSON mapping dosyasını DB'ye uygular. mode='merge': mevcut
        kayıtlar natural key ile (modül.name, point=(module_name,
        point_type, channel)) eşleştirilip güncellenir, eksik olanlar
        eklenir. mode='replace_points': mevcut tüm IO noktaları silinir
        sonra import edilir (modüller merge).
        Returns {'modules_added','modules_updated','points_added',
        'points_updated','points_skipped'}."""
        if not self._is_admin():
            raise PermissionDenied("Sadece admin mapping import edebilir.")
        if mode not in ('merge', 'replace_points'):
            raise ValueError("mode 'merge' veya 'replace_points' olmalı.")
        path = os.fspath(path)
        if not os.path.isfile(path):
            raise ValueError(f"Mapping dosyası bulunamadı: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if int(data.get('version', 0)) != self.MAPPING_VERSION:
            raise ValueError(
                f"Desteklenmeyen mapping versiyonu: {data.get('version')} "
                f"(beklenen {self.MAPPING_VERSION})")

        stats = {'modules_added': 0, 'modules_updated': 0,
                 'points_added': 0, 'points_updated': 0, 'points_skipped': 0}

        existing_mods = {m['name']: m for m in self.list_modules()}
        # ── Modüller (merge) ───────────────────────────────────
        for m in data.get('modules', []):
            name = (m.get('name') or '').strip()
            if not name:
                continue
            if name in existing_mods:
                mid = int(existing_mods[name]['id'])
                upd = {k: v for k, v in m.items() if k != 'name'}
                if upd:
                    self.update_module(mid, **upd)
                    stats['modules_updated'] += 1
            else:
                mid = self.add_module(
                    name=name,
                    host=m.get('host', ''),
                    port=int(m.get('port', 502)),
                    unit_id=int(m.get('unit_id', 255)),
                    mock_mode=int(m.get('mock_mode', 0)),
                    description=m.get('description', ''),
                    **{k: v for k, v in m.items() if k in (
                        'timeout_sec', 'output_start', 'output_count',
                        'input_start', 'input_count', 'ao_words', 'do_words',
                        'ai_words', 'di_words', 'raw_max', 'poll_ms', 'is_active')},
                )
                stats['modules_added'] += 1

        # Yeni eklenenleri de kapsayan güncel modül haritası
        name_to_id = {m['name']: int(m['id']) for m in self.list_modules()}

        # ── Noktalar ───────────────────────────────────────────
        if mode == 'replace_points':
            for p in self.list_points():
                try:
                    self.delete_point(int(p['id']))
                except Exception:
                    pass

        existing_points = {
            (int(p['module_id']), p['point_type'], int(p['channel'])): p
            for p in self.list_points()
        }
        link_allowed = {'name', 'unit', 'scale', 'offset', 'is_visible',
                        'sort_order', 'description', 'link_type', 'link_id',
                        'link_role', 'low_alarm', 'high_alarm'}

        for p in data.get('points', []):
            mod_name = p.get('module_name')
            mid = name_to_id.get(mod_name)
            if not mid:
                stats['points_skipped'] += 1
                continue
            pt = p.get('point_type')
            try:
                ch = int(p.get('channel'))
            except (TypeError, ValueError):
                stats['points_skipped'] += 1
                continue
            key = (mid, pt, ch)
            if key in existing_points:
                upd = {k: v for k, v in p.items() if k in link_allowed and v is not None}
                if upd:
                    self.update_point(int(existing_points[key]['id']), **upd)
                    stats['points_updated'] += 1
            else:
                try:
                    new_id = self.add_point(
                        module_id=mid, point_type=pt, channel=ch,
                        name=p.get('name', f"{pt}{ch}"),
                        unit=p.get('unit', ''),
                        scale=float(p.get('scale', 1.0) or 1.0),
                        offset=float(p.get('offset', 0.0) or 0.0),
                        is_visible=int(p.get('is_visible', 1)),
                        sort_order=int(p.get('sort_order', 0)),
                        description=p.get('description', ''),
                    )
                    # Link / alarm güncellemeleri (add_point bunları kabul etmez)
                    upd = {k: v for k, v in p.items()
                           if k in ('link_type', 'link_id', 'link_role',
                                    'low_alarm', 'high_alarm') and v is not None}
                    if upd:
                        self.update_point(new_id, **upd)
                    stats['points_added'] += 1
                except Exception:
                    stats['points_skipped'] += 1

        self._audit(
            'IO_MAPPING_IMPORT',
            f"IO mapping import edildi ← {path} mode={mode} stats={stats}",
            table_name='weidmuller_modules',
            new_value=str(stats),
        )
        return stats
