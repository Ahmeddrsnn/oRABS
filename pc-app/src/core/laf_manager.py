"""
LAF (Laminar Air Flow) Manager (Faz-5)
=======================================
Thin domain layer on top of `core.database.Database` for the LAF panel:
  - Sensor CRUD (`laf_sensors`)            -- admin-only mutations
  - 5-minute snapshot writes (`laf_readings`)
  - Device alarm flag log (`laf_alarm_events`)

All DB calls go through the shared Database (RLock-protected). This module
never opens its own sqlite cursor.

Audit policy (21 CFR Part 11)
- Sensor config changes → audit.log_action(category='LAF').
- Alarm raise/clear   → audit.log_action(category='LAF', action_type='LAF_ALARM').
- Snapshot writes are NOT audited (high volume; live in laf_readings table).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional


VALID_REGISTER_TYPES = ('holding', 'input')
VALID_DATA_TYPES = ('uint16', 'int16', 'uint32', 'int32', 'float32')


class PermissionDenied(Exception):
    """Raised when a non-admin attempts an admin-only mutation."""


class LafManager:
    """Domain operations for LAF sensors, readings and alarm events."""

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
               table_name: str = 'laf_sensors',
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
                category='LAF',
            )
        except Exception:
            import traceback
            traceback.print_exc()

    # ── Sensors ──────────────────────────────────────────────────
    def list_sensors(self, only_visible: bool = False,
                     only_overview: bool = False) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, label, sensor_type, register_addr, register_type, '
                   'data_type, scale, offset, unit, is_visible, '
                   'show_on_overview, sort_order, overview_x, overview_y '
                   'FROM laf_sensors')
            where = []
            if only_visible:
                where.append('is_visible=1')
            if only_overview:
                where.append('show_on_overview=1')
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY sort_order, id'
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def add_sensor(self, label: str, sensor_type: str, register_addr: int,
                   register_type: str = 'holding', data_type: str = 'uint16',
                   scale: float = 1.0, offset: float = 0.0, unit: str = '',
                   is_visible: int = 1, show_on_overview: int = 0,
                   sort_order: int = 0) -> int:
        if not self._is_admin():
            raise PermissionDenied("Sadece admin sensör ekleyebilir.")
        label = (label or '').strip()
        if not label:
            raise ValueError("Etiket boş olamaz.")
        if register_type not in VALID_REGISTER_TYPES:
            raise ValueError(f"register_type {VALID_REGISTER_TYPES} olmalı.")
        if data_type not in VALID_DATA_TYPES:
            raise ValueError(f"data_type {VALID_DATA_TYPES} olmalı.")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO laf_sensors
                   (label, sensor_type, register_addr, register_type, data_type,
                    scale, offset, unit, is_visible, show_on_overview, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (label, sensor_type, register_addr, register_type, data_type,
                 scale, offset, unit, is_visible, show_on_overview, sort_order),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        self._audit('LAF_SENSOR_ADD',
                    f"Sensör eklendi: {label} (reg {register_addr})",
                    record_id=new_id, new_value=label)
        return new_id

    def update_sensor(self, sensor_id: int, **fields):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin sensör güncelleyebilir.")
        if not fields:
            return
        allowed = {'label', 'sensor_type', 'register_addr', 'register_type',
                   'data_type', 'scale', 'offset', 'unit', 'is_visible',
                   'show_on_overview', 'sort_order'}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Bilinmeyen alan(lar): {bad}")
        if 'register_type' in fields and fields['register_type'] not in VALID_REGISTER_TYPES:
            raise ValueError("register_type geçersiz.")
        if 'data_type' in fields and fields['data_type'] not in VALID_DATA_TYPES:
            raise ValueError("data_type geçersiz.")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM laf_sensors WHERE id=?', (sensor_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Sensör bulunamadı: id={sensor_id}")
            old = dict(row)
            sets = ', '.join(f'{k}=?' for k in fields)
            params = list(fields.values()) + [sensor_id]
            cur.execute(f'UPDATE laf_sensors SET {sets} WHERE id=?', params)
            conn.commit()
        finally:
            self.db.close()

        changed = {k: (old.get(k), v) for k, v in fields.items() if old.get(k) != v}
        if changed:
            desc = f"Sensör #{sensor_id} güncellendi: " + ', '.join(
                f"{k}: {a}→{b}" for k, (a, b) in changed.items()
            )
            self._audit('LAF_SENSOR_UPDATE', desc, record_id=sensor_id,
                        old_value=str({k: a for k, (a, _) in changed.items()}),
                        new_value=str({k: b for k, (_, b) in changed.items()}))

    def delete_sensor(self, sensor_id: int):
        if not self._is_admin():
            raise PermissionDenied("Sadece admin sensör silebilir.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT label FROM laf_sensors WHERE id=?', (sensor_id,))
            row = cur.fetchone()
            if not row:
                return
            label = row['label']
            cur.execute('DELETE FROM laf_sensors WHERE id=?', (sensor_id,))
            conn.commit()
        finally:
            self.db.close()
        self._audit('LAF_SENSOR_DELETE',
                    f"Sensör silindi: {label} (id={sensor_id})",
                    record_id=sensor_id, old_value=label)

    # ── Snapshots ────────────────────────────────────────────────
    def add_snapshot(self, readings: Dict[int, Optional[float]],
                     timestamp: Optional[str] = None):
        """Persist a batch of readings. `readings` is {sensor_id: value|None}.

        Must be called from the GUI thread (Plan B: workers post via signals).
        """
        if not readings:
            return
        ts = timestamp or datetime.now().isoformat()
        rows = [(ts, sid, val) for sid, val in readings.items()]
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.executemany(
                'INSERT INTO laf_readings (timestamp, sensor_id, value) VALUES (?, ?, ?)',
                rows,
            )
            conn.commit()
        finally:
            self.db.close()

    def query_readings(self, start_iso: str, end_iso: str,
                       sensor_ids: Optional[List[int]] = None) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            if sensor_ids:
                placeholders = ','.join('?' * len(sensor_ids))
                cur.execute(
                    f'''SELECT r.timestamp, r.sensor_id, r.value,
                               s.label, s.unit
                        FROM laf_readings r
                        JOIN laf_sensors s ON s.id=r.sensor_id
                        WHERE r.timestamp BETWEEN ? AND ?
                          AND r.sensor_id IN ({placeholders})
                        ORDER BY r.timestamp''',
                    [start_iso, end_iso] + list(sensor_ids),
                )
            else:
                cur.execute(
                    '''SELECT r.timestamp, r.sensor_id, r.value,
                              s.label, s.unit
                       FROM laf_readings r
                       JOIN laf_sensors s ON s.id=r.sensor_id
                       WHERE r.timestamp BETWEEN ? AND ?
                       ORDER BY r.timestamp''',
                    (start_iso, end_iso),
                )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def latest_reading_per_sensor(self) -> Dict[int, Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''SELECT r.sensor_id, r.timestamp, r.value
                   FROM laf_readings r
                   JOIN (
                       SELECT sensor_id, MAX(timestamp) AS mts
                       FROM laf_readings GROUP BY sensor_id
                   ) m ON m.sensor_id=r.sensor_id AND m.mts=r.timestamp'''
            )
            return {r['sensor_id']: dict(r) for r in cur.fetchall()}
        finally:
            self.db.close()

    # ── Alarms ───────────────────────────────────────────────────
    def add_alarm(self, flag_code: str, message: str = '') -> int:
        """Record a device-reported alarm flag (raise event)."""
        ts = datetime.now().isoformat()
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO laf_alarm_events (timestamp, flag_code, message) VALUES (?, ?, ?)',
                (ts, flag_code, message),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()
        self._audit('LAF_ALARM',
                    f"Cihaz alarmı: {flag_code} {message}".strip(),
                    record_id=new_id, table_name='laf_alarm_events',
                    new_value=flag_code)
        return new_id

    def clear_alarm(self, alarm_id: int):
        ts = datetime.now().isoformat()
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'UPDATE laf_alarm_events SET cleared_at=? WHERE id=? AND cleared_at IS NULL',
                (ts, alarm_id),
            )
            conn.commit()
        finally:
            self.db.close()
        self._audit('LAF_ALARM_CLEAR', f"Alarm temizlendi: id={alarm_id}",
                    record_id=alarm_id, table_name='laf_alarm_events')

    def list_active_alarms(self) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, timestamp, flag_code, message FROM laf_alarm_events '
                'WHERE cleared_at IS NULL ORDER BY timestamp DESC'
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def list_recent_alarms(self, limit: int = 50) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, timestamp, flag_code, message, cleared_at '
                'FROM laf_alarm_events ORDER BY timestamp DESC LIMIT ?',
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    # ── Settings convenience ─────────────────────────────────────
    def get_settings(self) -> Dict[str, str]:
        keys = ('laf_com_port', 'laf_baud', 'laf_parity', 'laf_stop_bits',
                'laf_slave_id', 'laf_poll_sec', 'laf_snapshot_sec')
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            placeholders = ','.join('?' * len(keys))
            cur.execute(
                f'SELECT setting_key, setting_value FROM system_settings '
                f'WHERE setting_key IN ({placeholders})',
                keys,
            )
            return {r['setting_key']: r['setting_value'] for r in cur.fetchall()}
        finally:
            self.db.close()
