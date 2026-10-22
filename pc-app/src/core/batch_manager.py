"""
Oraps Batch Manager (Faz-4)
============================
Thin domain layer on top of `core.database.Database` for the Oraps app:
  - Door-lock configurations (`batch_door_config`)
  - Active batch singleton (`active_batch`)
  - Door labels (`oraps_door_labels`)

All database calls go through Database methods, which are protected by
the shared RLock (Plan B). This module never opens its own sqlite cursor.

Audit policy (21 CFR Part 11)
- Every mutation routes through `audit.log_action(category='ORAPS')`.
- Soft-delete only for configurations (CFR traceability).
- Permission checks (Admin vs Operator) are enforced here AND at the UI
  layer; UI is a convenience, this layer is the source of truth.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional


# Kapı/port sayısı GLB'ye göre dinamik olarak `oraps_door_labels` /
# `oraps_port_labels` tablolarından okunur (bkz. get_door_count / get_port_count).
# Aşağıdaki sabitler:
#   - DEFAULT_*  : Tablolar boşsa/reinit edilmediyse döner (schema seed).
#   - MAX_*      : Validasyon üst sınırı = reinit_doors_for_glb cap'i.
#   - DOOR_COUNT / PORT_COUNT : Modül dışına export'lu, geriye dönük
#     uyumluluk için tutulur; yeni kodda `self.get_door_count()` /
#     `self.get_port_count()` kullanın.
DEFAULT_DOOR_COUNT = 12    # MN-180 elektromanyetik kilitler (KLT-180-AS:1..12)
DEFAULT_PORT_COUNT = 14    # eldiven port montaj:1..14
MAX_DOOR_COUNT     = 64
MAX_PORT_COUNT     = 64
DOOR_COUNT = DEFAULT_DOOR_COUNT   # legacy alias
PORT_COUNT = DEFAULT_PORT_COUNT   # legacy alias


class PermissionDenied(Exception):
    """Raised when a non-admin attempts an admin-only mutation."""


class BatchInProgress(Exception):
    """Raised when an operation conflicts with the running batch."""


class BatchManager:
    """Domain operations for Oraps batches and door configurations."""

    def __init__(self, database, auth_manager, audit_manager=None):
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager

    # ── Helpers ──────────────────────────────────────────────────
    def _is_admin(self) -> bool:
        return self.auth.get_current_user_role() == 'Admin'

    def _can_manage_configs(self) -> bool:
        """Admin veya Supervisor batch şablonlarını/kapı-port etiketlerini
        yönetebilir. IO bağlama gibi donanım işlemleri ayrıca Admin-only."""
        role = self.auth.get_current_user_role()
        return role in ('Admin', 'Supervisor')

    def _current_user_id(self) -> Optional[int]:
        u = getattr(self.auth, 'current_user', None)
        return u.get('id') if u else None

    # ── Dinamik sayı okuyucular (aktif GLB'nin fiili kapı/port sayısı) ─
    def get_door_count(self) -> int:
        """Aktif GLB için tanımlı kapı sayısı = oraps_door_labels satır sayısı.
        Tablo boşsa (henüz reinit çağrılmamış olabilir) DEFAULT_DOOR_COUNT döner.
        """
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM oraps_door_labels')
            n = int(cur.fetchone()[0])
            return n if n > 0 else DEFAULT_DOOR_COUNT
        finally:
            self.db.close()

    def get_port_count(self) -> int:
        """Aktif GLB için tanımlı port sayısı = oraps_port_labels satır sayısı."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM oraps_port_labels')
            n = int(cur.fetchone()[0])
            return n if n > 0 else DEFAULT_PORT_COUNT
        finally:
            self.db.close()

    def _audit(self, action_type: str, description: str,
               record_id: Optional[int] = None,
               old_value: str = '', new_value: str = '',
               table_name: str = 'batch_door_config',
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
            # Audit failure must never block the operation, but we do not
            # silently swallow programmer errors — log to stderr.
            import traceback
            traceback.print_exc()

    # ── Door labels ──────────────────────────────────────────────
    def get_door_labels(self) -> List[Dict]:
        """Return list of {door_index, label, glb_node, is_visible,
        group_id, group_name, stop_group_id, show_label,
        overview_x, overview_y, overview_z}."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT d.door_index, d.label, d.glb_node, d.is_visible, '
                'd.group_id, g.name AS group_name, d.stop_group_id, '
                'd.show_label, '
                'd.overview_x, d.overview_y, d.overview_z '
                'FROM oraps_door_labels d '
                'LEFT JOIN oraps_door_groups g ON g.id=d.group_id '
                'ORDER BY d.door_index'
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def update_door_label(self, door_index: int, label: Optional[str] = None,
                          glb_node: Optional[str] = None,
                          is_visible: Optional[int] = None,
                          group_id: Optional[int] = -1,
                          show_label: Optional[int] = None,
                          stop_group_id: Optional[int] = -1):
        """Kapı etiketi/grubu güncelle.

        group_id: -1 → dokunma; None → gruptan çıkar; int → o gruba ata.
        stop_group_id: aynı semantik — makine durdurma grubu üyeliği
        (kilit grubundan bağımsız, Faz-10b).
        label/glb_node/is_visible/show_label None ise mevcut değer korunur.
        show_label: 3D'de bu kapının ad etiketini toptan toggle'a rağmen
        gizle/göster (Faz-5).
        """
        if not self._can_manage_configs():
            raise PermissionDenied("Kapı isimlerini sadece admin veya supervisor değiştirebilir.")
        if not 1 <= door_index <= MAX_DOOR_COUNT:
            raise ValueError(f"door_index 1..{MAX_DOOR_COUNT} aralığında olmalı, alınan: {door_index}")
        if label is not None:
            label = label.strip()   # '' izinli → isimsiz (viewer'da gizli)

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT label, glb_node, is_visible, group_id, show_label, '
                'stop_group_id '
                'FROM oraps_door_labels WHERE door_index=?',
                (door_index,),
            )
            row = cur.fetchone()
            old = dict(row) if row else None

            if label is None:
                label = old['label'] if old else f'Kapı {door_index}'
            if glb_node is None and old is not None:
                glb_node = old['glb_node']
            if is_visible is None:
                is_visible = old['is_visible'] if old else 1
            # group_id == -1 → mevcudu koru; aksi halde verilen değeri yaz.
            new_group_id = (old.get('group_id') if old else None) \
                if group_id == -1 else group_id
            new_stop_gid = (old.get('stop_group_id') if old else None) \
                if stop_group_id == -1 else stop_group_id
            if show_label is None:
                new_show_label = old.get('show_label') if old else 1
            else:
                new_show_label = 1 if show_label else 0

            cur.execute(
                '''INSERT INTO oraps_door_labels
                     (door_index, label, glb_node, is_visible, group_id,
                      show_label, stop_group_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(door_index) DO UPDATE SET
                     label=excluded.label,
                     glb_node=excluded.glb_node,
                     is_visible=excluded.is_visible,
                     group_id=excluded.group_id,
                     show_label=excluded.show_label,
                     stop_group_id=excluded.stop_group_id''',
                (door_index, label, glb_node, int(bool(is_visible)),
                 new_group_id, int(new_show_label), new_stop_gid),
            )
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'DOOR_LABEL_UPDATED',
            f"Kapı {door_index} etiketi güncellendi: '{label}'",
            record_id=door_index,
            old_value=json.dumps(old) if old else '',
            new_value=json.dumps({
                'door_index': door_index, 'label': label,
                'glb_node': glb_node, 'is_visible': is_visible,
                'group_id': new_group_id, 'show_label': new_show_label,
                'stop_group_id': new_stop_gid,
            }),
        )

    def reinit_doors_for_glb(self, door_count: int,
                             outer_flags: Optional[Dict[int, bool]] = None) -> Dict[str, int]:
        """`oraps_door_labels` tablosunu yeni GLB'nin kapı sayısına göre
        senkronla. `door_index > door_count` olan satırları siler, eksikleri
        default etiketle (`Kapı N`) ekler. Model her yüklendiğinde çağrılır;
        yetki kontrolü yoktur (otomatik senkron).

        outer_flags: {door_index: bool} — viewer'ın dış-yüzey sezgiseli. True
        (dış kapı) → yeni satır default is_visible=1; False (iç panel) → 0.
        Verilmezse tümü görünür (is_visible=1). MEVCUT satırların is_visible'ı
        ASLA ezilmez (kullanıcı elle ayarlamış olabilir).

        Returns: {'added': X, 'removed': Y, 'kept': Z}
        """
        if not isinstance(door_count, int) or door_count < 1 or door_count > MAX_DOOR_COUNT:
            raise ValueError(f"door_count 1..{MAX_DOOR_COUNT} aralığında olmalı, alınan: {door_count!r}")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT door_index FROM oraps_door_labels')
            existing = {int(r[0]) for r in cur.fetchall()}
            wanted = set(range(1, door_count + 1))

            to_remove = sorted(existing - wanted)
            to_add = sorted(wanted - existing)
            kept = len(existing & wanted)

            if to_remove:
                cur.executemany(
                    'DELETE FROM oraps_door_labels WHERE door_index=?',
                    [(i,) for i in to_remove],
                )
            if to_add:
                # Yeni kapılar İSİMSİZ eklenir (label=''); viewer'da yalnızca
                # kullanıcının isimlendirdiği kapılar sprite olarak görünür.
                cur.executemany(
                    'INSERT INTO oraps_door_labels '
                    '(door_index, label, glb_node, is_visible, group_id) '
                    "VALUES (?, '', NULL, 1, NULL)",
                    [(i,) for i in to_add],
                )
            conn.commit()
        finally:
            self.db.close()

        if to_add or to_remove:
            self._audit(
                'DOOR_LABELS_RESIZED',
                f"GLB yenilendi: kapı sayısı {door_count} "
                f"(eklendi: {len(to_add)}, silindi: {len(to_remove)}).",
                old_value=json.dumps(sorted(existing)),
                new_value=json.dumps(sorted(wanted)),
                table_name='oraps_door_labels',
            )

        return {'added': len(to_add), 'removed': len(to_remove), 'kept': kept}

    def reinit_ports_for_glb(self, port_count: int) -> Dict[str, int]:
        """`oraps_port_labels` tablosunu GLB'nin port sayısına senkronla.
        `port_index > port_count` satırları siler, eksikleri default etiketle
        (`Port N`) ekler. Model her yüklendiğinde çağrılır; yetki kontrolü
        yoktur (otomatik senkron). Yeni GLB'de 16 port varken DB'de 14 kalınca
        port 15/16 tıklamada 'bulunamadı' hatası veriyordu — bu onu çözer.

        Returns: {'added': X, 'removed': Y, 'kept': Z}
        """
        if not isinstance(port_count, int) or port_count < 1 or port_count > MAX_PORT_COUNT:
            raise ValueError(f"port_count 1..{MAX_PORT_COUNT} aralığında olmalı, alınan: {port_count!r}")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT port_index FROM oraps_port_labels')
            existing = {int(r[0]) for r in cur.fetchall()}
            wanted = set(range(1, port_count + 1))

            to_remove = sorted(existing - wanted)
            to_add = sorted(wanted - existing)
            kept = len(existing & wanted)

            if to_remove:
                cur.executemany(
                    'DELETE FROM oraps_port_labels WHERE port_index=?',
                    [(i,) for i in to_remove],
                )
            if to_add:
                # Yeni portlar İSİMSİZ eklenir (label=''); viewer'da yalnızca
                # isimlendirilen portlar sprite olarak görünür.
                cur.executemany(
                    'INSERT INTO oraps_port_labels '
                    '(port_index, label, glb_node, has_motion_sensor, is_visible) '
                    "VALUES (?, '', NULL, 0, 1)",
                    [(i,) for i in to_add],
                )
            conn.commit()
        finally:
            self.db.close()

        if to_add or to_remove:
            self._audit(
                'PORT_LABELS_RESIZED',
                f"GLB yenilendi: port sayısı {port_count} "
                f"(eklendi: {len(to_add)}, silindi: {len(to_remove)}).",
                old_value=json.dumps(sorted(existing)),
                new_value=json.dumps(sorted(wanted)),
                table_name='oraps_port_labels',
            )

        return {'added': len(to_add), 'removed': len(to_remove), 'kept': kept}

    # ── Door groups (v5) ─────────────────────────────────────────
    def list_door_groups(self) -> List[Dict]:
        """Return list of {id, name, description, member_count,
        stop_member_count}. member_count = kilit grubu (group_id) üyeleri,
        stop_member_count = makine durdurma (stop_group_id) üyeleri."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT g.id, g.name, g.description, '
                '       COUNT(DISTINCT d.door_index) AS member_count, '
                '       COUNT(DISTINCT s.door_index) AS stop_member_count '
                'FROM oraps_door_groups g '
                'LEFT JOIN oraps_door_labels d ON d.group_id=g.id '
                'LEFT JOIN oraps_door_labels s ON s.stop_group_id=g.id '
                'GROUP BY g.id ORDER BY g.name'
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def create_door_group(self, name: str, description: str = '') -> int:
        if not self._can_manage_configs():
            raise PermissionDenied("Kapı grubu oluşturmak için admin veya supervisor yetkisi gerekir.")
        name = (name or '').strip()
        if not name:
            raise ValueError("Grup adı boş olamaz.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO oraps_door_groups (name, description, created_at) '
                'VALUES (?, ?, ?)',
                (name, description or '', datetime.now().isoformat()),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()
        self._audit(
            'DOOR_GROUP_CREATE',
            f"Kapı grubu oluşturuldu: '{name}' (#{new_id})",
            record_id=new_id,
            new_value=json.dumps({'id': new_id, 'name': name,
                                  'description': description}),
        )
        return int(new_id)

    def delete_door_group(self, group_id: int):
        if not self._can_manage_configs():
            raise PermissionDenied("Kapı grubu silmek için admin veya supervisor yetkisi gerekir.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT name FROM oraps_door_groups WHERE id=?', (group_id,)
            )
            r = cur.fetchone()
            if not r:
                raise ValueError(f"Grup #{group_id} bulunamadı.")
            name = r['name']
            cur.execute(
                'UPDATE oraps_door_labels SET group_id=NULL WHERE group_id=?',
                (group_id,),
            )
            cur.execute(
                'UPDATE oraps_door_labels SET stop_group_id=NULL '
                'WHERE stop_group_id=?',
                (group_id,),
            )
            cur.execute(
                'DELETE FROM oraps_door_groups WHERE id=?', (group_id,)
            )
            conn.commit()
        finally:
            self.db.close()
        self._audit(
            'DOOR_GROUP_DELETE',
            f"Kapı grubu silindi: '{name}' (#{group_id})",
            record_id=group_id,
            old_value=json.dumps({'id': group_id, 'name': name}),
        )

    # ── Door-lock configurations ─────────────────────────────────
    def list_configs(self, include_inactive: bool = False) -> List[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, config_name, description, door_states, '
                   'created_by, created_at, modified_by, modified_at, is_active '
                   'FROM batch_door_config')
            if not include_inactive:
                sql += ' WHERE is_active=1'
            sql += ' ORDER BY config_name'
            cur.execute(sql)
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d['door_states'] = json.loads(d['door_states'])
                except (TypeError, ValueError):
                    d['door_states'] = {}
                d['open_count'] = sum(
                    1 for s in d['door_states'].values() if s == 'open'
                )
                # locked_count'u fiili dict'ten say → GLB'ye göre değişken
                # kapı sayısı ile uyumlu (eski: sabit 12 çıkarılırdı).
                d['locked_count'] = sum(
                    1 for s in d['door_states'].values() if s == 'locked'
                )
                rows.append(d)
            return rows
        finally:
            self.db.close()

    def get_config(self, config_id: int) -> Optional[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, config_name, description, door_states, port_indices, '
                'stop_group_ids, wait_glt_pass, is_active '
                'FROM batch_door_config WHERE id=?',
                (config_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d['door_states'] = json.loads(d['door_states'])
            except (TypeError, ValueError):
                d['door_states'] = {}
            try:
                d['port_indices'] = json.loads(d['port_indices']) if d.get('port_indices') else []
            except (TypeError, ValueError):
                d['port_indices'] = []
            # None = seçim yok (hepsi aktif); liste = açık seçim.
            try:
                d['stop_group_ids'] = (json.loads(d['stop_group_ids'])
                                       if d.get('stop_group_ids') else None)
            except (TypeError, ValueError):
                d['stop_group_ids'] = None
            try:
                d['wait_glt_pass'] = int(d.get('wait_glt_pass') or 0)
            except (TypeError, ValueError):
                d['wait_glt_pass'] = 0
            return d
        finally:
            self.db.close()

    def _normalise_states(self, door_states: Dict) -> Dict[str, str]:
        """Coerce input dict into {'idx': 'open'|'locked', ...}.
        Yalnızca input'ta belirtilen kapı indekslerini normalize eder.
        Input'ta olmayan kapılar eklenmez → viewer'da nötr kalır,
        DO yazılmaz (IO'ya bağlı olmayan kapaklar etkilenmez)."""
        norm: Dict[str, str] = {}
        for k, v in door_states.items():
            try:
                idx = str(int(k))
            except (TypeError, ValueError):
                continue
            state = str(v).lower()
            if state not in ('open', 'locked'):
                state = 'open'
            norm[idx] = state
        return norm

    def create_config(self, name: str, description: str,
                      door_states: Dict, port_indices: list = None,
                      stop_group_ids: list = None,
                      wait_glt_pass: int = 0) -> int:
        if not self._can_manage_configs():
            raise PermissionDenied("Yeni konfig oluşturmak için admin veya supervisor yetkisi gerekir.")
        name = (name or '').strip()
        if not name:
            raise ValueError("Konfig adı boş olamaz.")
        states_norm = self._normalise_states(door_states)
        ports_json = json.dumps(port_indices or [])
        # None = seçim yok (tüm machine_stop grupları aktif) → NULL saklanır;
        # liste (boş dahi olsa) açık seçimdir.
        stop_json = None if stop_group_ids is None else json.dumps(
            sorted({int(g) for g in stop_group_ids}))
        now = datetime.now().isoformat()

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO batch_door_config
                   (config_name, description, door_states, port_indices,
                    stop_group_ids, wait_glt_pass, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, description or '', json.dumps(states_norm), ports_json,
                 stop_json, int(bool(wait_glt_pass)),
                 self._current_user_id() or 1, now),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'CONFIG_CREATED',
            f"Yeni kapı konfigürasyonu oluşturuldu: '{name}' "
            f"(portlar: {port_indices or []}, durdurma grupları: "
            f"{'tümü' if stop_group_ids is None else sorted(set(stop_group_ids))}, "
            f"GLT bekle: {int(bool(wait_glt_pass))})",
            record_id=new_id,
            new_value=json.dumps({'name': name, 'states': states_norm,
                                  'ports': port_indices or [],
                                  'stop_groups': stop_group_ids,
                                  'wait_glt_pass': int(bool(wait_glt_pass))}),
        )
        return new_id

    def update_config(self, config_id: int, name: str, description: str,
                      door_states: Dict, port_indices: list = None,
                      stop_group_ids: list = None,
                      wait_glt_pass: int = 0):
        if not self._can_manage_configs():
            raise PermissionDenied("Konfig düzenlemek için admin veya supervisor yetkisi gerekir.")
        # Block edits if this config is the one currently in use
        ab = self.get_active_batch()
        if ab and ab.get('config_id') == config_id and ab.get('status') in ('running', 'paused'):
            raise BatchInProgress(
                "Bu konfig şu anda aktif batch tarafından kullanılıyor. "
                "Önce batch'i bitirin."
            )

        old = self.get_config(config_id)
        if not old:
            raise ValueError(f"Konfig bulunamadı (id={config_id})")

        name = (name or '').strip()
        if not name:
            raise ValueError("Konfig adı boş olamaz.")
        states_norm = self._normalise_states(door_states)
        ports_json = json.dumps(port_indices or [])
        stop_json = None if stop_group_ids is None else json.dumps(
            sorted({int(g) for g in stop_group_ids}))
        now = datetime.now().isoformat()

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''UPDATE batch_door_config
                   SET config_name=?, description=?, door_states=?, port_indices=?,
                       stop_group_ids=?, wait_glt_pass=?, modified_by=?, modified_at=?
                   WHERE id=?''',
                (name, description or '', json.dumps(states_norm), ports_json,
                 stop_json, int(bool(wait_glt_pass)),
                 self._current_user_id() or 1, now, config_id),
            )
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'CONFIG_UPDATED',
            f"Kapı konfigürasyonu güncellendi: '{name}'",
            record_id=config_id,
            old_value=json.dumps({'name': old['config_name'], 'states': old['door_states']}),
            new_value=json.dumps({'name': name, 'states': states_norm, 'ports': port_indices or []}),
        )

    def delete_config(self, config_id: int):
        """Soft delete — keeps history for audit (21 CFR Part 11)."""
        if not self._can_manage_configs():
            raise PermissionDenied("Konfig silmek için admin veya supervisor yetkisi gerekir.")
        ab = self.get_active_batch()
        if ab and ab.get('config_id') == config_id and ab.get('status') in ('running', 'paused'):
            raise BatchInProgress(
                "Aktif batch'in konfigi silinemez. Önce batch'i bitirin."
            )

        old = self.get_config(config_id)
        if not old:
            return  # nothing to delete

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'UPDATE batch_door_config SET is_active=0, modified_by=?, modified_at=? WHERE id=?',
                (self._current_user_id() or 1, datetime.now().isoformat(), config_id),
            )
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'CONFIG_DELETED',
            f"Kapı konfigürasyonu silindi (soft): '{old['config_name']}'",
            record_id=config_id,
            old_value=json.dumps({'name': old['config_name'], 'states': old['door_states']}),
        )

    # ── Active batch ─────────────────────────────────────────────
    def get_active_batch(self) -> Optional[Dict]:
        """Return current active_batch row (singleton id=1)."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''SELECT ab.id, ab.batch_name, ab.config_id, ab.started_by,
                          ab.started_at, ab.status, ab.port_indices, ab.phase,
                          c.config_name, c.stop_group_ids, c.wait_glt_pass,
                          COALESCE(ab.door_states, c.door_states) AS door_states,
                          u.username AS started_by_name
                   FROM active_batch ab
                   LEFT JOIN batch_door_config c ON c.id = ab.config_id
                   LEFT JOIN users u ON u.id = ab.started_by
                   WHERE ab.id = 1'''
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get('door_states'):
                try:
                    d['door_states'] = json.loads(d['door_states'])
                except (TypeError, ValueError):
                    d['door_states'] = {}
            else:
                d['door_states'] = {}
            if d.get('port_indices'):
                try:
                    d['port_indices'] = json.loads(d['port_indices'])
                except (TypeError, ValueError):
                    d['port_indices'] = []
            else:
                d['port_indices'] = []
            # Faz-10: makine durdurma grubu seçimi (config'ten).
            # None = seçim yok → tüm machine_stop grupları aktif.
            try:
                d['stop_group_ids'] = (json.loads(d['stop_group_ids'])
                                       if d.get('stop_group_ids') else None)
            except (TypeError, ValueError):
                d['stop_group_ids'] = None
            # Faz-12: aşama — NULL/boş = legacy tek aşamalı ('orabs' sayılır).
            d['phase'] = (d.get('phase') or 'orabs')
            try:
                d['wait_glt_pass'] = int(d.get('wait_glt_pass') or 0)
            except (TypeError, ValueError):
                d['wait_glt_pass'] = 0
            return d
        finally:
            self.db.close()

    def start_batch(self, batch_name: str, config_id: int):
        """Start a new batch using the given door configuration.
        Allowed for Operator and Admin (anyone logged in)."""
        if not self.auth.current_user:
            raise PermissionDenied("Önce giriş yapmalısınız.")
        batch_name = (batch_name or '').strip()
        if not batch_name:
            raise ValueError("Batch adı boş olamaz.")
        cfg = self.get_config(config_id)
        if not cfg or not cfg.get('is_active'):
            raise ValueError("Seçili konfig bulunamadı veya silinmiş.")

        ab = self.get_active_batch()
        if ab and ab.get('status') in ('running', 'paused'):
            raise BatchInProgress(
                f"Zaten aktif bir batch var: '{ab.get('batch_name')}'. "
                "Önce mevcut batch'i bitirin."
            )

        now = datetime.now().isoformat()
        ports_json = json.dumps(cfg.get('port_indices') or [])
        # Faz-12: config "önce GLT tamamlansın" diyorsa batch GLT aşamasında
        # başlar (kapılar açık, makine durdurulmuş); aksi halde doğrudan
        # ORABS aşaması (mevcut davranış).
        _phase = 'glt' if int(cfg.get('wait_glt_pass') or 0) else 'orabs'
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''UPDATE active_batch
                   SET batch_name=?, config_id=?, started_by=?,
                       started_at=?, status='running', door_states=NULL,
                       port_indices=?, phase=?
                   WHERE id=1''',
                (batch_name, config_id, self._current_user_id() or 1, now,
                 ports_json, _phase),
            )
            # Faz-8 birleşik akış (1/2): halihazırda aktif (standalone) GLT
            # batch varsa bu ORABS batch'e bağla → ORABS bitirilirken otomatik
            # kapatılır ve port test detayları özet rapora dahil edilir.
            cur.execute(
                "UPDATE test_batches SET linked_oraps_batch_id=1 "
                "WHERE status='ACTIVE' AND linked_oraps_batch_id IS NULL"
            )
            _n_linked = cur.rowcount
            # Bağlı ACTIVE GLT batch var mı? Yoksa aşağıda otomatik başlatılır.
            cur.execute(
                "SELECT COUNT(*) FROM test_batches "
                "WHERE status='ACTIVE' AND linked_oraps_batch_id=1"
            )
            _has_linked_glt = int(cur.fetchone()[0]) > 0
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'BATCH_STARTED',
            f"Batch başlatıldı: '{batch_name}' (konfig: {cfg['config_name']}, "
            f"aşama: {_phase.upper()})",
            record_id=config_id,
            new_value=json.dumps({'batch': batch_name, 'config_id': config_id,
                                  'phase': _phase}),
        )
        if _n_linked > 0:
            self._audit(
                'BATCH_GLT_LINKED',
                f"Aktif GLT batch ORABS batch'ine bağlandı: '{batch_name}' "
                f"({_n_linked} batch)",
            )

        # Faz-8 birleşik akış (2/2): bağlı GLT batch yoksa OTOMATİK başlat —
        # ORABS batch başlarken GLT batch de her zaman başlamış olur.
        if not _has_linked_glt:
            self._auto_start_linked_glt_batch(batch_name, cfg)

    def _resolve_glt_ports_for_indices(self, port_indices) -> List[Dict]:
        """ORABS port_index listesini GLT batch port kayıtlarına çevir:
        `oraps_port_labels.rfid_tag` → `glove_ports` eşleşmesi.
        Return: [{'port_id': int, 'rfid_tag': str}, ...] (dedup'lu)."""
        idxs = []
        for i in port_indices or []:
            try:
                idxs.append(int(i))
            except (TypeError, ValueError):
                continue
        if not idxs:
            return []
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            ph = ','.join('?' * len(idxs))
            cur.execute(
                'SELECT gp.id AS port_id, gp.rfid_tag AS rfid_tag '
                'FROM oraps_port_labels opl '
                'JOIN glove_ports gp '
                '  ON UPPER(TRIM(gp.rfid_tag)) = UPPER(TRIM(opl.rfid_tag)) '
                f"WHERE opl.port_index IN ({ph}) "
                "  AND IFNULL(TRIM(opl.rfid_tag), '') != ''",
                idxs,
            )
            out, seen = [], set()
            for r in cur.fetchall():
                pid = int(r['port_id'])
                if pid in seen:
                    continue
                seen.add(pid)
                out.append({'port_id': pid,
                            'rfid_tag': (r['rfid_tag'] or '').strip()})
            return out
        finally:
            self.db.close()

    def _auto_start_linked_glt_batch(self, batch_name: str, cfg: Dict):
        """ORABS batch başlarken bağlı GLT batch'i otomatik başlat.
        Ad = ORABS batch adı; portlar = konfigde seçili ORABS portlarının
        RFID eşleşmesiyle bulunan GLT portları. Hiç port çözülemezse GLT
        batch AÇILMAZ (boş batch / boş rapor üretmemek için) ve audit'e
        not düşülür."""
        glt_ports = self._resolve_glt_ports_for_indices(
            cfg.get('port_indices') or [])
        if not glt_ports:
            self._audit(
                'BATCH_GLT_SKIPPED',
                f"GLT batch otomatik başlatılmadı: '{batch_name}' konfiginde "
                "RFID eşleşmeli seçili port yok.",
            )
            return
        try:
            glt_id = self.db.create_batch(
                batch_name, self._current_user_id() or 1,
                linked_oraps_batch_id=1,
            )
        except Exception:
            glt_id = None
        if not glt_id:
            self._audit(
                'BATCH_GLT_SKIPPED',
                f"GLT batch otomatik başlatılamadı (DB hatası): '{batch_name}'",
            )
            return
        try:
            self.db.add_ports_to_batch(glt_id, glt_ports)
        except Exception:
            import traceback
            traceback.print_exc()
        self._audit(
            'BATCH_GLT_STARTED',
            f"GLT batch otomatik başlatıldı: '{batch_name}' "
            f"(#{glt_id}, {len(glt_ports)} port, ORABS'a bağlı)",
            record_id=glt_id,
            table_name='test_batches',
        )

    def advance_to_orabs_phase(self):
        """Faz-12: GLT aşamasından ORABS aşamasına geç — kilitler yazılır,
        makine durdurma normal mantığa döner. Port PASS/açıklama ve kapı
        kapalılık doğrulamaları UI tarafında yapılır (dialoglu akış);
        burası yalnız durum geçişini ve audit'i üstlenir."""
        if not self.auth.current_user:
            raise PermissionDenied("Önce giriş yapmalısınız.")
        ab = self.get_active_batch()
        if not ab or ab.get('status') not in ('running', 'paused'):
            raise BatchInProgress("Aktif batch yok.")
        if (ab.get('phase') or 'orabs') != 'glt':
            raise BatchInProgress("Batch zaten ORABS aşamasında.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE active_batch SET phase='orabs' WHERE id=1")
            conn.commit()
        finally:
            self.db.close()
        self._audit(
            'BATCH_PHASE_ORABS',
            f"GLT aşaması tamamlandı → ORABS aşamasına geçildi: "
            f"'{ab.get('batch_name')}'",
            table_name='active_batch',
        )

    def pause_batch(self):
        ab = self.get_active_batch()
        if not ab or ab.get('status') != 'running':
            raise BatchInProgress("Duraklatılabilir bir aktif batch yok.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE active_batch SET status='paused' WHERE id=1")
            conn.commit()
        finally:
            self.db.close()
        self._audit('BATCH_PAUSED', f"Batch duraklatıldı: '{ab.get('batch_name')}'")

    def system_interlock_pause(self, reason: str) -> bool:
        """Faz-6e: ışık bariyeri vb. ihlali nedeniyle sistem (bridge)
        tarafından yapılan otomatik duraklatma. Kullanıcı izni
        kontrolü yapmaz; sadece status='running' iken etki eder.
        Audit'e BATCH_INTERLOCK_TRIPPED + BATCH_PAUSED yazılır.
        Returns True if a pause was actually applied."""
        ab = self.get_active_batch()
        if not ab or ab.get('status') != 'running':
            return False
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE active_batch SET status='paused' WHERE id=1")
            conn.commit()
        finally:
            self.db.close()
        self._audit(
            'BATCH_INTERLOCK_TRIPPED',
            f"Otomatik duraklatma (interlock): {reason}",
            table_name='active_batch',
        )
        self._audit(
            'BATCH_PAUSED',
            f"Batch sistem tarafından duraklatıldı: '{ab.get('batch_name')}' "
            f"(interlock: {reason})",
            table_name='active_batch',
        )
        return True

    def resume_batch(self):
        ab = self.get_active_batch()
        if not ab or ab.get('status') != 'paused':
            raise BatchInProgress("Devam ettirilecek duraklatılmış batch yok.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE active_batch SET status='running' WHERE id=1")
            conn.commit()
        finally:
            self.db.close()
        self._audit('BATCH_RESUMED', f"Batch devam ettirildi: '{ab.get('batch_name')}'")

    def update_batch_door_states(self, door_states: Dict):
        """Aktif batch'in door_states JSON'ını güncelle (paused durumda
        kilit açma/kapama için). State değişikliği DB'ye yazılır."""
        import json as _json
        ab = self.get_active_batch()
        if not ab:
            raise BatchInProgress("Aktif batch yok.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE active_batch SET door_states=? WHERE id=1",
                (_json.dumps(door_states),),
            )
            conn.commit()
        finally:
            self.db.close()

    def clear_batch_door_states_override(self):
        """Runtime door_states override'ını temizle → config'teki orijinal
        state aktif olur. Batch devam ettirildiğinde çağrılır."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE active_batch SET door_states=NULL WHERE id=1")
            conn.commit()
        finally:
            self.db.close()

    def finish_batch(self):
        ab = self.get_active_batch()
        if not ab or ab.get('status') not in ('running', 'paused'):
            raise BatchInProgress("Bitirilecek aktif batch yok.")
        name = ab.get('batch_name')
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE active_batch
                   SET status='finished'
                   WHERE id=1"""
            )
            conn.commit()
        finally:
            self.db.close()
        self._audit('BATCH_FINISHED', f"Batch bitirildi: '{name}'")

    def clear_active_batch(self):
        """Admin-only hard reset — used by maintenance, not the normal UI."""
        if not self._is_admin():
            raise PermissionDenied("Sadece admin aktif batch kaydını sıfırlayabilir.")
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE active_batch
                   SET batch_name=NULL, config_id=NULL, started_by=NULL,
                       started_at=NULL, status='idle'
                   WHERE id=1"""
            )
            conn.commit()
        finally:
            self.db.close()
        self._audit('BATCH_CLEARED', "Aktif batch sıfırlandı (admin)")

    # ── Port labels (eldiven port:1..14) ─────────────────────────
    def get_port_labels(self) -> List[Dict]:
        """Return list of {port_index, label, glb_node, has_motion_sensor,
        is_visible, rfid_tag, show_label, overview_x, overview_y,
        overview_z}."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT port_index, label, glb_node, has_motion_sensor, '
                'is_visible, rfid_tag, show_label, '
                'overview_x, overview_y, overview_z '
                'FROM oraps_port_labels ORDER BY port_index'
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def list_registered_glt_rfids(self) -> List[Dict]:
        """GLT'de kayıtlı (glove_ports tablosundaki) RFID etiketlerini döndür
        ORAPS port eşleştirme picker'ı için. Boş/NULL RFID kayıtları filtrelenir."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, name, rfid_tag, recipe_id FROM glove_ports '
                "WHERE rfid_tag IS NOT NULL AND TRIM(rfid_tag) != '' "
                'ORDER BY name COLLATE NOCASE'
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.db.close()

    def update_port_label(self, port_index: int,
                          label: Optional[str] = None,
                          has_motion_sensor: Optional[int] = None,
                          glb_node: Optional[str] = None,
                          is_visible: Optional[int] = None,
                          rfid_tag: Optional[str] = None,
                          show_label: Optional[int] = None):
        if not self._can_manage_configs():
            raise PermissionDenied("Port ayarlarını sadece admin veya supervisor değiştirebilir.")
        if not 1 <= port_index <= MAX_PORT_COUNT:
            raise ValueError(f"port_index 1..{MAX_PORT_COUNT} aralığında olmalı, alınan: {port_index}")

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT label, glb_node, has_motion_sensor, is_visible, rfid_tag '
                'FROM oraps_port_labels WHERE port_index=?', (port_index,)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Port {port_index} bulunamadı.")
            old_label = row['label']
            old_motion = row['has_motion_sensor']
            old_rfid = row['rfid_tag']

            sets, vals = [], []
            if label is not None:
                label = label.strip()   # '' izinli → isimsiz
                sets.append('label=?'); vals.append(label)
            if has_motion_sensor is not None:
                sets.append('has_motion_sensor=?'); vals.append(1 if has_motion_sensor else 0)
            if glb_node is not None:
                sets.append('glb_node=?'); vals.append(glb_node)
            if is_visible is not None:
                sets.append('is_visible=?'); vals.append(1 if is_visible else 0)
            if rfid_tag is not None:
                # Boş string → NULL (eslemeyi kaldır)
                new_rfid_val: Optional[str] = rfid_tag.strip() if rfid_tag else None
                if new_rfid_val == '':
                    new_rfid_val = None
                # 1:1 kısıtlama: aynı RFID başka porta atanmış mı?
                if new_rfid_val is not None:
                    cur.execute(
                        'SELECT port_index FROM oraps_port_labels '
                        'WHERE rfid_tag=? AND port_index!=?',
                        (new_rfid_val, port_index),
                    )
                    conflict = cur.fetchone()
                    if conflict:
                        raise ValueError(
                            f"Bu RFID etiketi zaten Port {conflict['port_index']}'e atanmış. "
                            "Bir RFID yalnızca bir porta atanabilir."
                        )
                sets.append('rfid_tag=?'); vals.append(new_rfid_val)
            if show_label is not None:
                sets.append('show_label=?'); vals.append(1 if show_label else 0)
            if not sets:
                return
            vals.append(port_index)
            cur.execute(
                f"UPDATE oraps_port_labels SET {', '.join(sets)} WHERE port_index=?",
                vals,
            )
            conn.commit()
        finally:
            self.db.close()

        # Audit
        descs = []
        if label is not None and label != old_label:
            descs.append(f"isim: '{old_label}' → '{label}'")
        if has_motion_sensor is not None and bool(has_motion_sensor) != bool(old_motion):
            descs.append(f"hareket sensörü: {'AÇIK' if has_motion_sensor else 'KAPALI'}")
        if rfid_tag is not None:
            new_rfid_val = (rfid_tag or '').strip() or None
            if (old_rfid or None) != new_rfid_val:
                descs.append(
                    f"RFID: '{old_rfid or '-'}' → '{new_rfid_val or '-'}'"
                )
        if descs:
            self._audit(
                'PORT_UPDATED',
                f"Port {port_index} güncellendi — {'; '.join(descs)}",
                record_id=port_index,
                table_name='oraps_port_labels',
                old_value=f"{old_label} / motion={old_motion} / rfid={old_rfid or '-'}",
                new_value=f"{label or old_label} / motion={has_motion_sensor if has_motion_sensor is not None else old_motion} / rfid={(rfid_tag or '').strip() or old_rfid or '-'}",
            )

    # ── IO event audit hooks (called by Faz-5 Modbus worker) ─────
    # Faz-9: audit description'ı Türkçeleştir (kullanıcı "Kapak N açıldı /
    # kapatıldı" gibi okunur satırlar istiyor).
    _DOOR_EVENT_TR = {
        'OPENED':   'açıldı',
        'CLOSED':   'kapatıldı',
        'LOCKED':   'kilitlendi',
        'UNLOCKED': 'kilidi açıldı',
        'FORCED':   'zorlandı',
        'FORCED_CLOSED': 'kapatıldı (kilitliyken açılmıştı)',
    }

    def log_door_io_event(self, door_index: int, event: str,
                          source: str = 'IO'):
        """Audit log for a hardware door state change.

        event: 'OPENED' | 'CLOSED' | 'LOCKED' | 'UNLOCKED' | 'FORCED'
        source: usually 'IO' (Weidmüller) or 'MANUAL'.
        """
        if not 1 <= door_index <= MAX_DOOR_COUNT:
            return
        labels = {d['door_index']: d['label'] for d in self.get_door_labels()}
        name = labels.get(door_index) or f'Kapı {door_index}'
        tr = self._DOOR_EVENT_TR.get(str(event).upper(),
                                     str(event).lower())
        self._audit(
            f'DOOR_{event}',
            f"{name} {tr}",
            record_id=door_index,
            table_name='oraps_door_labels',
            new_value=event,
        )

    def log_port_motion_event(self, port_index: int, detected: bool,
                              source: str = 'IO'):
        """Audit log for a glove-port motion sensor trigger.
        Also updates oraps_port_labels.is_occupied + last_motion_ts so the
        UI can reflect current state without re-replaying audit history."""
        if not 1 <= port_index <= MAX_PORT_COUNT:
            return
        labels = {p['port_index']: p['label'] for p in self.get_port_labels()}
        # Kullanıcı label vermemişse (label='') fallback: "Port <index>".
        # labels.get(port_index) '' döndürebilir → `or` ile boş string durumu
        # da yakalanır; aksi halde description "  — hareket ..." gibi baştaki
        # tire yalın kalıyordu (Faz-8 fix).
        name = labels.get(port_index) or f"Port {port_index}"
        ts = datetime.now().isoformat(timespec='seconds')
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'UPDATE oraps_port_labels SET is_occupied=?, last_motion_ts=? '
                'WHERE port_index=?',
                (1 if detected else 0, ts, port_index),
            )
            conn.commit()
        finally:
            self.db.close()
        self._audit(
            'PORT_MOTION' if detected else 'PORT_MOTION_END',
            f"{name} hareket {'algılandı' if detected else 'sona erdi'} ({source})",
            record_id=port_index,
            table_name='oraps_port_labels',
            new_value='detected' if detected else 'ended',
        )

    def get_port_occupancy(self) -> Dict[int, Dict]:
        """{port_index: {'is_occupied': 0/1, 'last_motion_ts': iso or None}}"""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT port_index, is_occupied, last_motion_ts '
                'FROM oraps_port_labels'
            )
            return {
                r['port_index']: {
                    'is_occupied': int(r['is_occupied'] or 0),
                    'last_motion_ts': r['last_motion_ts'],
                }
                for r in cur.fetchall()
            }
        finally:
            self.db.close()

    # ── Light barriers (Faz-6c) ──────────────────────────────────
    @staticmethod
    def _parse_door_indices(raw) -> List[int]:
        """DB'deki door_indices JSON string'ini list[int]'e çevir. Boş/geçersiz
        değerde [] döner."""
        if not raw:
            return []
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(v, list):
                return [int(x) for x in v if isinstance(x, (int, float, str))
                        and str(x).strip() != '']
        except Exception:
            pass
        return []

    def _augment_barrier(self, row: Dict) -> Dict:
        """DB satırına door_indices (list[int]) alanını ekler. door_indices
        JSON'u boşsa legacy door_a_index/door_b_index'ten üretir."""
        idxs = self._parse_door_indices(row.get('door_indices'))
        if not idxs:
            a, b = int(row.get('door_a_index') or 0), int(row.get('door_b_index') or 0)
            idxs = sorted({a, b} - {0})
        row['door_indices'] = idxs
        return row

    def list_barriers(self, only_active: bool = False) -> List[Dict]:
        """Tüm ışık bariyerlerini döner. Her satırda door_indices: List[int]."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            sql = ('SELECT id, label, door_a_index, door_b_index, door_indices, '
                   'is_active, description, created_at FROM light_barriers')
            if only_active:
                sql += ' WHERE is_active=1'
            sql += ' ORDER BY label'
            cur.execute(sql)
            return [self._augment_barrier(dict(r)) for r in cur.fetchall()]
        finally:
            self.db.close()

    def get_barrier(self, barrier_id: int) -> Optional[Dict]:
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM light_barriers WHERE id=?', (barrier_id,))
            row = cur.fetchone()
            return self._augment_barrier(dict(row)) if row else None
        finally:
            self.db.close()

    def _normalize_barrier_doors(self, a: int, b: int):
        """Legacy iki-kapı normalize (geriye uyum: eski çağrılar için)."""
        n = self.get_door_count()
        if not (1 <= a <= n and 1 <= b <= n):
            raise ValueError(f"Kapı indeksleri 1..{n} olmalı (aktif GLB için).")
        if a == b:
            raise ValueError("Bariyerin iki ucu aynı kapı olamaz.")
        return (a, b) if a < b else (b, a)

    def _normalize_barrier_door_list(self, doors) -> List[int]:
        """N-kapı normalize: [1..MAX] içi unique sıralı list. En az 1 kapı."""
        n = self.get_door_count()
        try:
            idxs = sorted({int(d) for d in (doors or [])})
        except (TypeError, ValueError):
            raise ValueError("Geçersiz kapı listesi.")
        if not idxs:
            raise ValueError("Bariyere en az 1 kapı seçilmeli.")
        for d in idxs:
            if not 1 <= d <= n:
                raise ValueError(
                    f"Kapı indeksleri 1..{n} olmalı (aktif GLB için)."
                )
        return idxs

    def add_barrier(self, label: str, door_a_index: Optional[int] = None,
                    door_b_index: Optional[int] = None,
                    description: str = '', is_active: int = 1,
                    door_indices: Optional[list] = None) -> int:
        """Işık bariyeri ekle. Yeni imza: `door_indices=[1,3,5]`. Legacy imza
        `door_a_index / door_b_index` da desteklenir (2 kapı)."""
        if not self._can_manage_configs():
            raise PermissionDenied("Işık bariyeri eklemek için admin veya supervisor yetkisi gerekir.")
        label = (label or '').strip()
        if not label:
            raise ValueError("Bariyer etiketi boş olamaz.")
        # Kaynak: yeni door_indices; yoksa legacy a/b
        if door_indices is None and door_a_index is not None and door_b_index is not None:
            door_indices = [int(door_a_index), int(door_b_index)]
        idxs = self._normalize_barrier_door_list(door_indices)
        # Legacy a/b: 1 kapılı bariyer için a=b (CHECK yok yeni tabloda).
        # 2+ kapılı için min/max yaz.
        legacy_a = idxs[0]
        legacy_b = idxs[-1] if len(idxs) > 1 else idxs[0]

        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO light_barriers
                   (label, door_a_index, door_b_index, door_indices,
                    is_active, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (label, legacy_a, legacy_b, json.dumps(idxs),
                 int(bool(is_active)), description,
                 datetime.now().isoformat()),
            )
            new_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'BARRIER_CREATE',
            f"Işık bariyeri '{label}' eklendi (Kapılar: "
            f"{', '.join(str(i) for i in idxs)})",
            record_id=new_id,
            table_name='light_barriers',
            new_value=json.dumps({
                'label': label, 'door_indices': idxs,
                'is_active': int(bool(is_active)),
            }),
        )
        return new_id

    def update_barrier(self, barrier_id: int, **fields):
        if not self._can_manage_configs():
            raise PermissionDenied("Işık bariyerini güncellemek için admin veya supervisor yetkisi gerekir.")
        allowed = {'label', 'door_a_index', 'door_b_index', 'door_indices',
                   'is_active', 'description'}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Geçersiz alanlar: {bad}")

        old = self.get_barrier(barrier_id)
        if not old:
            raise ValueError(f"Bariyer #{barrier_id} bulunamadı.")

        # Kapı listesi güncellenmişse yeni door_indices'i normalize et.
        # Öncelik: door_indices > (a,b) çifti > eski değer.
        new_idxs = None
        if 'door_indices' in fields and fields['door_indices'] is not None:
            new_idxs = self._normalize_barrier_door_list(fields['door_indices'])
        elif 'door_a_index' in fields or 'door_b_index' in fields:
            a = int(fields.get('door_a_index', old['door_a_index']))
            b = int(fields.get('door_b_index', old['door_b_index']))
            new_idxs = self._normalize_barrier_door_list([a, b])

        if new_idxs is not None:
            fields['door_indices'] = json.dumps(new_idxs)
            fields['door_a_index'] = new_idxs[0]
            fields['door_b_index'] = new_idxs[-1] if len(new_idxs) > 1 else new_idxs[0]
        else:
            # door_* dokunulmadıysa alanları set setinden çıkar
            fields.pop('door_a_index', None)
            fields.pop('door_b_index', None)
            fields.pop('door_indices', None)

        if 'label' in fields:
            fields['label'] = (fields['label'] or '').strip()
            if not fields['label']:
                raise ValueError("Bariyer etiketi boş olamaz.")
        if 'is_active' in fields:
            fields['is_active'] = int(bool(fields['is_active']))

        if not fields:
            return

        sets = ', '.join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [barrier_id]
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(f"UPDATE light_barriers SET {sets} WHERE id=?", vals)
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'BARRIER_UPDATE',
            f"Bariyer #{barrier_id} güncellendi",
            record_id=barrier_id,
            table_name='light_barriers',
            old_value=json.dumps({k: old.get(k) for k in fields}),
            new_value=json.dumps(fields),
        )

    def delete_barrier(self, barrier_id: int):
        if not self._can_manage_configs():
            raise PermissionDenied("Işık bariyerini silmek için admin veya supervisor yetkisi gerekir.")
        old = self.get_barrier(barrier_id)
        if not old:
            return
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute('DELETE FROM light_barriers WHERE id=?', (barrier_id,))
            conn.commit()
        finally:
            self.db.close()

        self._audit(
            'BARRIER_DELETE',
            f"Bariyer '{old['label']}' (Kapılar: "
            f"{', '.join(str(i) for i in (old.get('door_indices') or []))}) silindi",
            record_id=barrier_id,
            table_name='light_barriers',
            old_value=json.dumps(old),
        )

    # ── Faz-6d: Light barrier events (worker bridge) ─────────────
    def record_barrier_event(self, barrier_id: int, module_id: int,
                             channel: int, state: int,
                             ts: Optional[str] = None) -> Optional[int]:
        """IO worker köprüsü: DI'da bir kenar (rising/falling) algılandığında
        olayı kaydeder, BARRIER_TRIGGERED audit'i atar.

        Returns inserted event id, or None if barrier no longer exists.
        Permission: no check — worker thread is the only caller, system-level.
        """
        if state not in (0, 1):
            raise ValueError(f"state must be 0 or 1, got {state}")
        barrier = self.get_barrier(int(barrier_id))
        if not barrier:
            return None
        ts = ts or datetime.now().isoformat(timespec='seconds')
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO light_barrier_events '
                '(barrier_id, module_id, channel, state, ts) '
                'VALUES (?, ?, ?, ?, ?)',
                (int(barrier_id), int(module_id), int(channel), int(state), ts),
            )
            event_id = cur.lastrowid
            conn.commit()
        finally:
            self.db.close()

        edge = 'BLOKE' if state == 1 else 'serbest'
        _idxs = barrier.get('door_indices') or []
        if not _idxs:
            _idxs = sorted({int(barrier['door_a_index']),
                            int(barrier['door_b_index'])})
        # Kapı adları: kullanıcı etiketi varsa o, yoksa 'Kapı N'.
        try:
            _lbls = {d['door_index']: (d.get('label') or '').strip()
                     for d in self.get_door_labels()}
        except Exception:
            _lbls = {}
        _names = ', '.join(_lbls.get(int(i)) or f'Kapı {i}' for i in _idxs)
        # Modül/DI kanal detayı açıklamada gösterilmez (new_value
        # JSON'unda saklanır) — operatör için sade metin.
        self._audit(
            'BARRIER_TRIGGERED',
            f"Bariyer '{barrier['label']}' ({_names}) {edge}",
            record_id=int(barrier_id),
            table_name='light_barriers',
            new_value=json.dumps({
                'state': int(state), 'module_id': int(module_id),
                'channel': int(channel), 'ts': ts,
                'door_indices': _idxs,
            }),
        )
        return event_id

    def list_recent_barrier_events(self, limit: int = 20,
                                   barrier_id: Optional[int] = None
                                   ) -> List[Dict]:
        """Son N olayı yeni→eski sırada döner. barrier_id verilirse
        sadece o bariyerin olayları."""
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            if barrier_id is not None:
                cur.execute(
                    'SELECT id, barrier_id, module_id, channel, state, ts '
                    'FROM light_barrier_events WHERE barrier_id=? '
                    'ORDER BY ts DESC, id DESC LIMIT ?',
                    (int(barrier_id), int(limit)),
                )
            else:
                cur.execute(
                    'SELECT id, barrier_id, module_id, channel, state, ts '
                    'FROM light_barrier_events '
                    'ORDER BY ts DESC, id DESC LIMIT ?',
                    (int(limit),),
                )
            rows = cur.fetchall()
        finally:
            self.db.close()
        return [
            {'id': r[0], 'barrier_id': r[1], 'module_id': r[2],
             'channel': r[3], 'state': r[4], 'ts': r[5]}
            for r in rows
        ]

    def purge_old_barrier_events(self, days: Optional[int] = None) -> int:
        """Faz-6h housekeeping: light_barrier_events tablosundan eski
        kayıtları siler (operasyonel olay logu; audit_trail §11.10(c)
        gereği ASLA silinmez). `days=None` ise system_settings'tan
        `oraps_lbe_retention_days` okunur; 0 → devre dışı (silinmez).

        Returns the number of rows deleted. Sadece admin çalıştırabilir.
        """
        if not self._is_admin():
            raise PermissionDenied("Sadece admin housekeeping çalıştırabilir.")
        if days is None:
            try:
                days = int(self.db.get_setting('oraps_lbe_retention_days', '90'))
            except (TypeError, ValueError):
                days = 90
        days = int(days)
        if days <= 0:
            return 0
        conn = self.db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM light_barrier_events "
                "WHERE ts < datetime('now', ?)",
                (f'-{days} days',),
            )
            deleted = cur.rowcount
            conn.commit()
        finally:
            self.db.close()
        if deleted:
            self._audit(
                'BARRIER_EVENTS_PURGED',
                f"{deleted} eski light_barrier_events kaydı silindi "
                f"(retention={days} gün)",
                table_name='light_barrier_events',
                new_value=str(deleted),
            )
        return deleted

