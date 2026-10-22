"""
Database module for 21 CFR Part 11 compliant data storage
Provides user management, test records, audit trails, and data integrity

Thread-safety (Plan B, 2026-06-16):
    All public methods are wrapped with @_synchronized so that concurrent
    callers (GLT GUI thread, Oraps Modbus worker, ESP32 read/process threads)
    can safely use the same Database instance. The connection itself opens
    with check_same_thread=False, journal_mode=WAL, and a 30s lock timeout
    so SQLite-level contention is handled gracefully.
"""

import sqlite3
import hashlib
import json
import random
import threading
from datetime import datetime
from functools import wraps
from typing import Optional, List, Dict, Any
import os
from utils.app_logger import get_logger

_logger = get_logger("database")


def normalize_rfid(tag) -> str:
    """RFID'yi kanonik forma çevir: '0x' prefix'i ve baştaki sıfırlar atılır,
    büyük harfe çevrilir. '0x00DA0DAE', 'da0dae', ' 0X00DA0DAE ' → 'DA0DAE'.
    Cihaz (kısa hex) ile PC kayıtları ('0x00...' formatı) arasındaki
    eşleşme sorunlarını tek noktadan çözer (bug 2026-08-03: test PASS
    olduğu halde batch_ports.status güncellenmiyordu)."""
    s = str(tag or '').strip().upper()
    if s.startswith('0X'):
        s = s[2:]
    s = s.lstrip('0')
    return s


def _synchronized(method):
    """Acquire the instance RLock around the wrapped Database method.

    RLock is re-entrant so internal calls (e.g. a wrapped method calling
    another wrapped method on the same instance) do not deadlock.
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Database:
    """SQLite database handler with 21 CFR Part 11 compliance features"""
    
    def __init__(self, db_path: str = "database/glove_test.db"):
        self.db_path = db_path
        # Re-entrant lock shared by every @_synchronized method.
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # Per-thread connection state. Each thread gets its OWN sqlite3
        # connection (check_same_thread=False allows handle reuse, but we
        # still isolate so that one thread's close() never invalidates
        # another thread's in-flight cursor — that was the source of
        # 'sqlite3.ProgrammingError: Cannot operate on a closed database'
        # crashes when ORAPS Weidmüller workers ran alongside GUI panels).
        # ``_local.depth`` is a refcount so nested connect/close pairs in
        # the same thread don't tear down the connection prematurely.
        self._local = threading.local()
        self.conn = None  # legacy alias; not relied on by any caller
        self.initialize_database()

    def _local_state(self):
        if not hasattr(self._local, 'conn'):
            self._local.conn = None
            self._local.depth = 0
        return self._local

    def connect(self):
        """Establish (or reuse) THIS thread's database connection.

        WAL + 30s lock timeout keep concurrent readers/writers happy at
        the SQLite level; per-thread handles keep `cursor.close()` semantics
        thread-local at the Python level.
        """
        l = self._local_state()
        if l.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            l.conn = conn
            l.depth = 0
        l.depth += 1
        self.conn = l.conn  # legacy alias for any stale reference
        return l.conn

    def close(self):
        """Close THIS thread's connection when its outermost user is done.

        Refcounted so nested connect/close pairs in a single thread keep
        the handle alive across the whole call tree.
        """
        l = self._local_state()
        if l.conn is None:
            return
        l.depth -= 1
        if l.depth > 0:
            return
        try:
            l.conn.close()
        except Exception:
            pass
        l.conn = None
        l.depth = 0
    
    def initialize_database(self):
        """Create database tables if they don't exist"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                email TEXT,
                is_active INTEGER DEFAULT 1,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                modified_at TEXT,
                modified_by TEXT,
                must_change_password INTEGER DEFAULT 0,
                password_changed_at TEXT
            )
        ''')
        
        # Check and migrate table if column missing
        self._check_and_migrate_users()
        
        # Test records table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT UNIQUE NOT NULL,
                operator_id INTEGER NOT NULL,
                glove_batch_number TEXT NOT NULL,
                glove_type TEXT NOT NULL,
                test_start_time TEXT NOT NULL,
                test_end_time TEXT,
                target_pressure REAL,
                target_temperature REAL,
                test_duration INTEGER,
                test_status TEXT NOT NULL,
                test_result TEXT,
                data_json TEXT,
                data_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                modified_at TEXT,
                FOREIGN KEY (operator_id) REFERENCES users(id)
            )
        ''')
        
        # Migrate test_records: add device_id column
        self._check_and_migrate_test_records()
        
        # Electronic signatures table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS electronic_signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                signature_meaning TEXT NOT NULL,
                signed_data_hash TEXT NOT NULL,
                signature_timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Audit trail table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL,
                action_type TEXT NOT NULL,
                table_name TEXT,
                record_id INTEGER,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                description TEXT,
                ip_address TEXT,
                category TEXT DEFAULT 'SYSTEM',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Audit trail migration (add category to existing DBs)
        self._check_and_migrate_audit_trail()
        
        # System events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT
            )
        ''')
        
        # Recipes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                glove_type TEXT NOT NULL,
                p1_pressure INTEGER NOT NULL DEFAULT 500,    -- Test/Start pressure (Pa)
                p2_hysteresis INTEGER NOT NULL DEFAULT 50,   -- Hysteresis (Pa)
                p3_limit INTEGER NOT NULL DEFAULT 100,       -- Acceptance limit (Pa)
                t1_inflation INTEGER NOT NULL DEFAULT 10,    -- Inflation time (s)
                t2_stabilization INTEGER NOT NULL DEFAULT 10,-- Stabilization time (s)
                t3_measurement INTEGER NOT NULL DEFAULT 60,  -- Measurement time (s)
                p8_success_drop INTEGER NOT NULL DEFAULT 200,-- Test end max drop (Pa)
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_by TEXT,
                created_at TEXT NOT NULL,
                modified_at TEXT
            )
        ''')
        
        
        # Check migration for recipes table
        self._check_and_migrate_recipes()
        
        # Layout Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS layout_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT,
                scale_factor REAL DEFAULT 1.0
            )
        ''')
        
        # Glove Ports table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS glove_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                x_pos INTEGER NOT NULL,
                y_pos INTEGER NOT NULL,
                rfid_tag TEXT,
                recipe_id INTEGER,
                last_updated TEXT,
                FOREIGN KEY (recipe_id) REFERENCES recipes(id)
            )
        ''')
        
        # System Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        ''')
        
        # Initialize default settings
        defaults = [
            ('auto_logout_minutes', '15'),
            ('company_logo_path', 'assets/logo.jpg')
        ]
        for key, val in defaults:
            cursor.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)', (key, val))

        # Test Batches table (Toplu Test)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_name TEXT NOT NULL,
                operator_id INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                linked_oraps_batch_id INTEGER,
                FOREIGN KEY (operator_id) REFERENCES users(id)
            )
        ''')
        # Migrate test_batches: add linked_oraps_batch_id column (Faz-6)
        self._check_and_migrate_test_batches()

        # Batch Ports table (Batch'e bağlı portlar)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batch_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                port_id INTEGER NOT NULL,
                rfid_tag TEXT,
                test_record_id INTEGER,
                status TEXT NOT NULL DEFAULT 'PENDING',
                explanation TEXT,
                FOREIGN KEY (batch_id) REFERENCES test_batches(id),
                FOREIGN KEY (test_record_id) REFERENCES test_records(id)
            )
        ''')

        # ── Batch Şablonları ──
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batch_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT NOT NULL UNIQUE,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batch_template_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                port_id INTEGER NOT NULL,
                FOREIGN KEY (template_id) REFERENCES batch_templates(id) ON DELETE CASCADE,
                FOREIGN KEY (port_id) REFERENCES glove_ports(id)
            )
        ''')

        # ── ORAPS (Faz-4) ────────────────────────────────────────────
        # Schema v2 (2026-06-18): 12 doors (KLT-180-AS:N) + 14 ports
        # (eldiven port montaj:N). Earlier schema had 14 doors mapped to
        # ports; corrected after CAD review (12 elektromanyetik kilit).
        # Migration: drop old door-related tables if v1 is detected.
        cursor.execute("SELECT setting_value FROM system_settings "
                       "WHERE setting_key='oraps_schema_version'")
        _row = cursor.fetchone()
        _current_v = int(_row[0]) if _row else 0
        if _current_v < 2:
            cursor.execute("DROP TABLE IF EXISTS batch_door_config")
            cursor.execute("DROP TABLE IF EXISTS active_batch")
            cursor.execute("DROP TABLE IF EXISTS oraps_door_labels")
            cursor.execute("DROP TABLE IF EXISTS oraps_port_labels")

        # Door-lock configurations: which of the 12 doors are open/locked
        # for a given batch profile. door_states is JSON
        # {"1":"open","2":"locked",...}. port_indices is JSON array of
        # selected port indices [3,5,7,...]. Soft-delete via is_active=0.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS batch_door_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_name TEXT NOT NULL UNIQUE,
                description TEXT,
                door_states TEXT NOT NULL,
                port_indices TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                modified_by INTEGER,
                modified_at TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

        # Singleton row holding the currently running Oraps batch.
        # status: 'idle' | 'running' | 'paused' | 'finished'.
        # door_states: runtime override — batch sırasında kilit açma/kapama
        # yapılırsa buraya yazılır. NULL ise config'teki orijinal kullanılır.
        # port_indices: JSON array — batch'e dahil edilen port indeksleri.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_batch (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                batch_name TEXT,
                config_id INTEGER,
                started_by INTEGER,
                started_at TEXT,
                status TEXT DEFAULT 'idle',
                door_states TEXT,
                port_indices TEXT,
                FOREIGN KEY (config_id) REFERENCES batch_door_config(id),
                FOREIGN KEY (started_by) REFERENCES users(id)
            )
        ''')
        cursor.execute(
            "INSERT OR IGNORE INTO active_batch (id, status) VALUES (1, 'idle')"
        )
        # Migration: door_states + port_indices kolonu yoksa ekle (eski DB uyumu).
        cursor.execute("PRAGMA table_info(active_batch)")
        _ab_cols = [info[1] for info in cursor.fetchall()]
        if 'door_states' not in _ab_cols:
            try:
                cursor.execute("ALTER TABLE active_batch ADD COLUMN door_states TEXT")
                conn.commit()
            except Exception:
                pass
        if 'port_indices' not in _ab_cols:
            try:
                cursor.execute("ALTER TABLE active_batch ADD COLUMN port_indices TEXT")
                conn.commit()
            except Exception:
                pass
        # Faz-12: iki aşamalı batch — 'glt' (GLT testleri sürüyor, kapılar
        # açık, makine durdurulmuş) | 'orabs' (normal akış). NULL = legacy
        # tek aşamalı batch ('orabs' sayılır).
        if 'phase' not in _ab_cols:
            try:
                cursor.execute("ALTER TABLE active_batch ADD COLUMN phase TEXT")
                conn.commit()
            except Exception:
                pass
        # Migration: batch_door_config.port_indices kolonu yoksa ekle.
        cursor.execute("PRAGMA table_info(batch_door_config)")
        _bdc_cols = [info[1] for info in cursor.fetchall()]
        if 'port_indices' not in _bdc_cols:
            try:
                cursor.execute("ALTER TABLE batch_door_config ADD COLUMN port_indices TEXT")
                conn.commit()
            except Exception:
                pass
        # Migration (Faz-10): makine durdurma grubu seçimi. JSON grup id
        # listesi; NULL = seçim yapılmamış (tüm machine_stop grupları aktif).
        if 'stop_group_ids' not in _bdc_cols:
            try:
                cursor.execute("ALTER TABLE batch_door_config ADD COLUMN stop_group_ids TEXT")
                conn.commit()
            except Exception:
                pass
        # Migration (Faz-12): 1 = önce GLT batch'i tamamlansın (tüm portlar
        # test edilmeden ORABS aşamasına geçilmez).
        if 'wait_glt_pass' not in _bdc_cols:
            try:
                cursor.execute("ALTER TABLE batch_door_config ADD COLUMN "
                               "wait_glt_pass INTEGER DEFAULT 0")
                conn.commit()
            except Exception:
                pass
        # Eski config'leri sil: port_indices NULL olan (eski format) config'ler
        # artık kullanılamaz; temiz başlangıç.
        try:
            cursor.execute(
                "DELETE FROM batch_door_config WHERE port_indices IS NULL"
            )
            conn.commit()
        except Exception:
            pass

        # User-editable labels mapping physical door index (1..12) to a
        # display label and the matching GLB scene node name (KLT-180-AS:N).
        # group_id (v5): kapıyı bir oraps_door_groups satırına bağlar; NULL
        # = gruba ait değil. Bir kapı tek bir gruba ait olabilir.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oraps_door_labels (
                door_index INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                glb_node TEXT,
                is_visible INTEGER DEFAULT 1,
                group_id INTEGER,
                overview_x REAL,
                overview_y REAL,
                overview_z REAL
            )
        ''')
        # v4→v5 migration: group_id kolonunu mevcut tabloya ekle.
        try:
            cursor.execute(
                'ALTER TABLE oraps_door_labels ADD COLUMN group_id INTEGER'
            )
        except Exception:
            pass  # zaten var
        # Faz-5 overlay: kapı ad etiketinin 3D dünya-ofset konumu (dx,dy,dz).
        for _col in ('overview_x', 'overview_y', 'overview_z'):
            try:
                cursor.execute(
                    f'ALTER TABLE oraps_door_labels ADD COLUMN {_col} REAL'
                )
            except Exception:
                pass  # zaten var
        # Faz-7: kullanıcı bu kapının etiketini toptan "Ad Etiketleri"
        # toggle'ına rağmen gizlemek isterse show_label=0 yazar.
        try:
            cursor.execute(
                'ALTER TABLE oraps_door_labels ADD COLUMN '
                'show_label INTEGER NOT NULL DEFAULT 1'
            )
        except Exception:
            pass  # zaten var
        # Faz-10b: makine durdurma grubu üyeliği — kilit grubundan (group_id)
        # BAĞIMSIZ ikinci üyelik. Bir kapı aynı anda hem kilit hem durdurma
        # grubunda olabilir.
        try:
            cursor.execute(
                'ALTER TABLE oraps_door_labels ADD COLUMN stop_group_id INTEGER'
            )
        except Exception:
            pass  # zaten var

        # Kapı grupları (v5): bir gruba ait kapılar tek IO çıkışıyla beraber
        # sürülebilir (weidmuller_io_points.link_type='door_group').
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oraps_door_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        ''')

        # Rapor kayıt defteri (2026-08-06): batch/özet raporlarının
        # üretim parametreleri DB'de kalır — PDF diskten silinse bile
        # Rapor Arşivi'nde görünür ve çift tıkla yeniden üretilebilir.
        # UNIQUE(report_kind, file_path): aynı rapor tekrar üretilince
        # satır güncellenir (batch adları yeniden kullanılabildiği için
        # dosya yolu doğal anahtar).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oraps_report_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_kind TEXT NOT NULL,
                batch_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_iso TEXT,
                end_iso TEXT,
                status TEXT,
                linked_glt_id INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(report_kind, file_path)
            )
        ''')

        # Acil stop butonları (v5): IO girişine (DI) bağlanabilir; ileride
        # birden fazla acil stop tanımlamak için liste olarak modellendi.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oraps_estop_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        ''')

        # Glove port labels (1..14) + optional motion sensor flag.
        # has_motion_sensor=1 → IO worker raises ORAPS_PORT_MOTION audit.
        # is_occupied / last_motion_ts populated by IoPanel DI edge bridge.
        # rfid_tag (v4): GLT tarafında kayıtlı bir RFID etiketi ile eşleştirme;
        # 3D viewer'da port mesh'ine tıklanıp RFID picker’dan seçilir.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oraps_port_labels (
                port_index INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                glb_node TEXT,
                has_motion_sensor INTEGER DEFAULT 0,
                is_visible INTEGER DEFAULT 1,
                is_occupied INTEGER DEFAULT 0,
                last_motion_ts TEXT,
                rfid_tag TEXT,
                overview_x REAL,
                overview_y REAL,
                overview_z REAL
            )
        ''')
        # v2→v3 migration: add the two new columns if table predates this.
        # v3→v4 migration: add rfid_tag column.
        # Faz-5 overlay: add overview_x/y/z (port ad etiketi 3D ofset).
        for col, ddl in (
            ('is_occupied', 'INTEGER DEFAULT 0'),
            ('last_motion_ts', 'TEXT'),
            ('rfid_tag', 'TEXT'),
            ('overview_x', 'REAL'),
            ('overview_y', 'REAL'),
            ('overview_z', 'REAL'),
            ('show_label', 'INTEGER NOT NULL DEFAULT 1'),
        ):
            try:
                cursor.execute(
                    f'ALTER TABLE oraps_port_labels ADD COLUMN {col} {ddl}'
                )
            except Exception:
                pass  # already exists

        # Faz-6c: Light barriers. Bariyer artık N kapıya bağlanabilir
        # (JSON `door_indices`). Geriye dönük uyum için eski `door_a_index /
        # door_b_index` kolonları korunur — yeni kayıtlarda min/max olarak
        # doldurulur (CHECK a<b ihlal edilmesin). Tek-kapılı bariyerler için
        # door_a_index=door_b_index'e izin vermek üzere CHECK kaldırıldı
        # (yeni tabloda). Eski DB'lerde CHECK duruyor olabilir — orada
        # add_barrier() min<max olacak şekilde iki farklı kapı zorunlu kılar
        # (tek-kapılı bariyer için schema'yı bir sonraki temiz kurulumda
        # rebuild ederiz).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS light_barriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                door_a_index INTEGER NOT NULL,
                door_b_index INTEGER NOT NULL,
                door_indices TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        ''')
        # Migration: mevcut DB'lerde door_indices kolonu yoksa ekle.
        try:
            cursor.execute(
                "ALTER TABLE light_barriers ADD COLUMN door_indices TEXT DEFAULT ''"
            )
        except Exception:
            pass  # zaten var
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_light_barriers_active '
            'ON light_barriers(is_active)'
        )

        # Faz-6d: Light barrier trigger events. Inserted by the IO worker
        # bridge when a DI bound to a barrier changes state (rising/falling
        # edges). No FK on barrier_id — kept for history even if the
        # barrier or IO link is later deleted.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS light_barrier_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barrier_id INTEGER NOT NULL,
                module_id INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                state INTEGER NOT NULL,
                ts TEXT NOT NULL
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_lbe_barrier_ts '
            'ON light_barrier_events(barrier_id, ts DESC)'
        )

        # ── Kablosuz IR bariyer sensörleri (Faz-7, 2026-07-06) ────────────
        # Slave-Master ESP-NOW üzerinden, master USB CDC ile PC'ye bağlı.
        # Her sensör MAC ile tanımlanır (auto-discover); UI'da MAC gösterilmez,
        # kullanıcı "Bariyer #N · Etiket · Port" görür. port_index bağlıysa
        # E1 mesajı → oraps port motion event → 3D'de mavi boyanır + audit.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS barrier_sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac TEXT NOT NULL UNIQUE,
                label TEXT DEFAULT '',
                port_index INTEGER,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                last_seen_ts TEXT,
                last_state TEXT,
                last_battery_mv INTEGER,
                created_at TEXT NOT NULL
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_barrier_sensors_port '
            'ON barrier_sensors(port_index)'
        )

        # Default Oraps settings
        # NOT: `oraps_glb_path` bilerek BOŞ bırakıldı. Sıfır kurulum sonrası
        # kullanıcı kendi GLB modelini Ayarlar → ORAPS ekranından yükler.
        oraps_defaults = [
            ('oraps_glb_path',         ''),
            ('oraps_glb_unit',         'cm'),
            ('oraps_weidmuller_ip',    '192.168.0.222'),
            ('oraps_weidmuller_port',  '502'),
            ('oraps_polling_ms',       '100'),
            ('oraps_mapping_path',     ''),
            ('oraps_di_debounce_ms',   '100'),
            ('oraps_barrier_auto_pause', '0'),
            ('oraps_machine_stop_idle', '0'),
            ('oraps_lbe_retention_days', '90'),
            ('oraps_overview_views',   'front,back,left,right'),
            ('barrier_com_port',       ''),
            ('barrier_motion_hold_ms', '5000'),
            ('barrier_low_battery_mv', '3200'),
            ('oraps_schema_version',   '6'),
        ]
        for k, v in oraps_defaults:
            cursor.execute(
                'INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
                (k, v),
            )
        # Force schema version to 6 in case it was lower (we just migrated).
        cursor.execute(
            "UPDATE system_settings SET setting_value='6' "
            "WHERE setting_key='oraps_schema_version'"
        )

        # Seed default door labels (1..12) — KLT-180-AS assemblies
        # Seed door label ROWS (1..12) İSİMSİZ (label=''). Viewer'da yalnızca
        # kullanıcının isimlendirdiği kapılar sprite olarak görünür. Satırlar
        # kilit/config eşlemesi için yine de tanımlı gelir (reinit GLB'ye göre
        # genişletir/daraltır).
        for i in range(1, 13):
            cursor.execute(
                'INSERT OR IGNORE INTO oraps_door_labels (door_index, label, glb_node) VALUES (?, ?, ?)',
                (i, '', None),
            )

        # Seed default emergency stop button (v5) — admins ekleyebilir.
        from datetime import datetime as _dt_estop
        cursor.execute(
            'INSERT OR IGNORE INTO oraps_estop_buttons '
            '(id, label, description, is_enabled, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (1, 'Ana Acil Stop', 'Sistem ana acil durdurma butonu',
             1, _dt_estop.now().isoformat()),
        )

        # Seed port label ROWS (1..14) İSİMSİZ (label='').
        for i in range(1, 15):
            cursor.execute(
                'INSERT OR IGNORE INTO oraps_port_labels '
                '(port_index, label, glb_node, has_motion_sensor) VALUES (?, ?, ?, ?)',
                (i, '', None, 0),
            )

        # v5→v6 tek seferlik: otomatik üretilmiş 'Kapı N' / 'Port N' etiketlerini
        # temizle (yeni felsefe: kapı/port adı yalnızca kullanıcı verince görünür).
        if _current_v < 6:
            for _pat in ('Kapı [0-9]', 'Kapı [0-9][0-9]'):
                cursor.execute(
                    "UPDATE oraps_door_labels SET label='' WHERE label GLOB ?",
                    (_pat,),
                )
            for _pat in ('Port [0-9]', 'Port [0-9][0-9]'):
                cursor.execute(
                    "UPDATE oraps_port_labels SET label='' WHERE label GLOB ?",
                    (_pat,),
                )

        # Seed default door-lock configurations: all-open and all-locked
        from datetime import datetime as _dt
        import json as _json
        _all_open   = _json.dumps({str(i): 'open'   for i in range(1, 13)})
        _all_locked = _json.dumps({str(i): 'locked' for i in range(1, 13)})
        _now = _dt.now().isoformat()
        cursor.execute(
            '''INSERT OR IGNORE INTO batch_door_config
               (config_name, description, door_states, created_by, created_at)
               VALUES (?, ?, ?, ?, ?)''',
            ('Hepsi Açık', 'Tüm 12 kapı açık (test/bakım)', _all_open, 1, _now),
        )
        cursor.execute(
            '''INSERT OR IGNORE INTO batch_door_config
               (config_name, description, door_states, created_by, created_at)
               VALUES (?, ?, ?, ?, ?)''',
            ('Hepsi Kilitli', 'Tüm 12 kapı kilitli (acil durum)', _all_locked, 1, _now),
        )

        # ── LAF (Faz-5) ──────────────────────────────────────────────
        # Laminar Air Flow ünitesi — USB→Modbus RTU dönüştürücü üzerinden
        # clean room monitör kartından okunur. Tek ünite, 9 dinamik sensör
        # (kullanıcı Settings'ten ekler/çıkarır), 5dk periyotlu DB snapshot.
        cursor.execute(
            "SELECT setting_value FROM system_settings "
            "WHERE setting_key='laf_schema_version'"
        )
        _laf_row = cursor.fetchone()
        _laf_v = int(_laf_row[0]) if _laf_row else 0
        # v2: add 'show_on_overview' column (ORAPS Genel Bakış—ayrı bayrak,
        # 'is_visible' LAF sekmesi görünürlüğünü kontrol etmeye devam eder).

        # Per-sensor configuration. register_type: 'holding'|'input'.
        # data_type: 'uint16'|'int16'|'uint32'|'int32'|'float32'.
        # value_db = (raw * scale) + offset.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laf_sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                register_addr INTEGER NOT NULL DEFAULT 0,
                register_type TEXT NOT NULL DEFAULT 'holding',
                data_type TEXT NOT NULL DEFAULT 'uint16',
                scale REAL NOT NULL DEFAULT 1.0,
                offset REAL NOT NULL DEFAULT 0.0,
                unit TEXT NOT NULL DEFAULT '',
                is_visible INTEGER NOT NULL DEFAULT 1,
                show_on_overview INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                overview_x REAL,
                overview_y REAL
            )
        ''')
        # Faz-5: drag-place pozisyon kolonları (idempotent ALTER eski DB'ler için)
        self._check_and_migrate_laf_sensors_position()
        # Eski (v1) DB'ler için 'show_on_overview' kolonunu sonradan ekle.
        if _laf_v < 2:
            try:
                cursor.execute(
                    'ALTER TABLE laf_sensors ADD COLUMN '
                    'show_on_overview INTEGER NOT NULL DEFAULT 0'
                )
            except Exception:
                # Kolon zaten varsa SQLite hata döner — yoksay.
                pass
        # 5dk snapshot tablosu — raporlama için. value NULL = okuma hatası.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laf_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                sensor_id INTEGER NOT NULL,
                value REAL,
                FOREIGN KEY (sensor_id) REFERENCES laf_sensors(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_laf_readings_ts ON laf_readings(timestamp)'
        )
        # Cihazın kendi alarm bayrakları (eşik tanımı yok — kullanıcı kararı).
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laf_alarm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                flag_code TEXT NOT NULL,
                message TEXT,
                cleared_at TEXT
            )
        ''')

        # Default LAF settings. Mock mod kald\u0131r\u0131ld\u0131 \u2014 worker daima Modbus RTU
        # dener; port kapal\u0131yken "Modbus bekleniyor" stat\u00fcs\u00fc g\u00f6r\u00fcnt\u00fclenir.
        laf_defaults = [
            ('laf_schema_version',  '2'),
            ('laf_com_port',        ''),
            ('laf_baud',            '19200'),
            ('laf_parity',          'N'),
            ('laf_stop_bits',       '1'),
            ('laf_slave_id',        '1'),
            ('laf_poll_sec',        '5'),
            ('laf_snapshot_sec',    '300'),
        ]
        for k, v in laf_defaults:
            cursor.execute(
                'INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
                (k, v),
            )
        # Eski DB'lerde versiyonu da güncelle
        if _laf_v < 2:
            cursor.execute(
                "UPDATE system_settings SET setting_value='2' "
                "WHERE setting_key='laf_schema_version'"
            )

        # Seed 9 default sensors (register adresleri placeholder — admin
        # Settings > LAF Sensörleri'nden cihaz dökümanına göre düzenler).
        laf_sensor_seed = [
            ('Hava Hızı',          'air_velocity',    0x4024, 'holding', 'int16',  0.1, 0.0, 'm/s', 1, 10),
            ('Sıcaklık',           'temperature',     0x4014, 'holding', 'int16',  0.1, 0.0, '°C',  1, 20),
            ('Nem',                'humidity',        0x401A, 'holding', 'int16',  0.1, 0.0, '%RH', 1, 30),
            ('Basınç',             'pressure',        0x400E, 'holding', 'int16',  0.1, 0.0, 'Pa',  1, 40),
            ('Kapı Durumu',        'door_state',      0x4000, 'holding', 'uint16', 1.0, 0.0, '',    1, 50),
            ('Kapı Kilidi',        'door_lock_state', 0x4131, 'holding', 'uint16', 1.0, 0.0, '',    1, 60),
            ('Aydınlatma',         'light_state',     0x4092, 'holding', 'uint16', 1.0, 0.0, '',    1, 70),
        ]
        cursor.execute('SELECT COUNT(*) FROM laf_sensors')
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                '''INSERT INTO laf_sensors
                   (label, sensor_type, register_addr, register_type, data_type,
                    scale, offset, unit, is_visible, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                laf_sensor_seed,
            )

        # ── Weidmüller IO (Faz-6a) ───────────────────────────────────
        # UR20-FBC-MOD-TCP coupler — Modbus TCP, sadece holding register
        # (FC03/FC06/FC16). Process Input @ 0x0000, Process Output @ 0x0800.
        # Çoklu modül desteği: her cihazın kendi IO haritası DB'de tutulur.
        # Gerçek donanım (2026-07): UR20-FBC-MOD-TCP-ECO +
        # Slot1:16DI-P + Slot2:16DI-P + Slot3:16DO-P → 32 DI + 16 DO,
        # AI/AO YOK. Process Input = 2 word DI, Process Output = 1 word DO.
        cursor.execute(
            "SELECT setting_value FROM system_settings "
            "WHERE setting_key='weidmuller_schema_version'"
        )
        _wm_row = cursor.fetchone()
        _wm_v = int(_wm_row[0]) if _wm_row else 0
        # Reserved for future destructive migrations; v1 = initial schema.

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weidmuller_modules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                host TEXT NOT NULL DEFAULT '192.168.0.222',
                port INTEGER NOT NULL DEFAULT 502,
                unit_id INTEGER NOT NULL DEFAULT 255,
                timeout_sec REAL NOT NULL DEFAULT 2.0,
                output_start INTEGER NOT NULL DEFAULT 2048,
                output_count INTEGER NOT NULL DEFAULT 16,
                input_start INTEGER NOT NULL DEFAULT 0,
                input_count INTEGER NOT NULL DEFAULT 32,
                ao_words INTEGER NOT NULL DEFAULT 0,
                do_words INTEGER NOT NULL DEFAULT 1,
                ai_words INTEGER NOT NULL DEFAULT 0,
                di_words INTEGER NOT NULL DEFAULT 2,
                raw_max INTEGER NOT NULL DEFAULT 27648,
                poll_ms INTEGER NOT NULL DEFAULT 500,
                is_active INTEGER NOT NULL DEFAULT 1,
                mock_mode INTEGER NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        ''')
        # Mantıksal kanal eşleme: point_type = DI/DO/AI/AO, channel = 0..15.
        # Worker, modül ayarlarından register adresini çözer; bu tablo
        # sadece insanın okuyabileceği etiket + ölçek bilgisi taşır.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weidmuller_io_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER NOT NULL,
                point_type TEXT NOT NULL,
                channel INTEGER NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                scale REAL NOT NULL DEFAULT 1.0,
                offset REAL NOT NULL DEFAULT 0.0,
                is_visible INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                link_type TEXT,
                link_id INTEGER,
                link_role TEXT DEFAULT '',
                low_alarm REAL,
                high_alarm REAL,
                FOREIGN KEY (module_id) REFERENCES weidmuller_modules(id) ON DELETE CASCADE,
                UNIQUE(module_id, point_type, channel)
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_wm_points_module '
            'ON weidmuller_io_points(module_id)'
        )
        # Migration: existing DBs without link_* columns get them added.
        cursor.execute("PRAGMA table_info(weidmuller_io_points)")
        _wm_pt_cols = {c[1] for c in cursor.fetchall()}
        for _c, _ddl in (
            ('link_type', 'ALTER TABLE weidmuller_io_points ADD COLUMN link_type TEXT'),
            ('link_id',   'ALTER TABLE weidmuller_io_points ADD COLUMN link_id INTEGER'),
            ('link_role', 'ALTER TABLE weidmuller_io_points ADD COLUMN link_role TEXT DEFAULT \'\''),
            # Faz-6g: AI alarm eşikleri (NULL = devre dışı). Worker karşılaştırırken
            # ölçeklenmiş mühendislik değerini (scale*raw+offset) kullanır.
            ('low_alarm',  'ALTER TABLE weidmuller_io_points ADD COLUMN low_alarm REAL'),
            ('high_alarm', 'ALTER TABLE weidmuller_io_points ADD COLUMN high_alarm REAL'),
        ):
            if _c not in _wm_pt_cols:
                try:
                    cursor.execute(_ddl)
                except Exception as _e:
                    _logger.warning("Migration error (weidmuller %s): %s", _c, _e)
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_wm_points_link '
            'ON weidmuller_io_points(link_type, link_id)'
        )

        weidmuller_defaults = [
            ('weidmuller_schema_version', '3'),
        ]
        for k, v in weidmuller_defaults:
            cursor.execute(
                'INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
                (k, v),
            )

        # Schema v2 migration: 8 → 16 DI/DO genişlet. Eski DB'lerde
        # DI8..15 ve DO8..15 satırlarını ekle (UNIQUE → çakışırsa atla).
        cursor.execute(
            "SELECT setting_value FROM system_settings "
            "WHERE setting_key='weidmuller_schema_version'"
        )
        _ver_row = cursor.fetchone()
        try:
            _wm_ver = int(_ver_row[0]) if _ver_row else 1
        except (TypeError, ValueError):
            _wm_ver = 1
        if _wm_ver < 2:
            cursor.execute('SELECT id FROM weidmuller_modules')
            _mods = [r[0] for r in cursor.fetchall()]
            for _mid in _mods:
                _extra = []
                for _ch in range(8, 16):
                    _extra.append((_mid, 'DI', _ch, f'DI{_ch+1}', '', 1.0, 0.0, 1, 100 + _ch, ''))
                    _extra.append((_mid, 'DO', _ch, f'DO{_ch+1}', '', 1.0, 0.0, 1, 200 + _ch, ''))
                cursor.executemany(
                    '''INSERT OR IGNORE INTO weidmuller_io_points
                       (module_id, point_type, channel, name, unit, scale, offset,
                        is_visible, sort_order, description)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    _extra,
                )
            cursor.execute(
                "UPDATE system_settings SET setting_value='2' "
                "WHERE setting_key='weidmuller_schema_version'"
            )
            _logger.info("Weidmüller schema migrated 1 → 2 (16 DI/DO seed)")

        # Schema v3 migration: fabrika-default register haritası (4AI+4AO+
        # 1 word DI + 16 word input) gerçek donanımla uyuşmuyordu → DI
        # bitleri in_regs[4]'ten okunuyor, bağlantı OK göründüğü halde
        # veri hep 0 geliyordu. YALNIZCA dokunulmamış modülleri yeni
        # haritaya taşı: register haritası hâlâ eski fabrika değerlerinde
        # VE hiçbir IO noktasına link kurulmamış. Elle yapılandırılmış
        # modüller (örn. dev makinesi: di_words=2) olduğu gibi kalır.
        if _wm_ver < 3:
            cursor.execute(
                'SELECT id FROM weidmuller_modules '
                'WHERE ai_words=4 AND ao_words=4 AND di_words=1 '
                'AND do_words=1 AND input_count=16'
            )
            _stale_mods = [r[0] for r in cursor.fetchall()]
            for _mid in _stale_mods:
                cursor.execute(
                    'SELECT COUNT(*) FROM weidmuller_io_points '
                    'WHERE module_id=? AND link_type IS NOT NULL', (_mid,)
                )
                if cursor.fetchone()[0]:
                    continue  # kullanıcı yapılandırmış — dokunma
                cursor.execute(
                    'UPDATE weidmuller_modules SET input_count=32, di_words=2, '
                    'ai_words=0, ao_words=0, description=? WHERE id=?',
                    ('UR20-FBC-MOD-TCP-ECO + Slot1:16DI-P + Slot2:16DI-P '
                     '+ Slot3:16DO-P', _mid),
                )
                # Donanımda olmayan AI/AO noktalarını kaldır
                cursor.execute(
                    "DELETE FROM weidmuller_io_points "
                    "WHERE module_id=? AND point_type IN ('AI', 'AO')", (_mid,)
                )
                # Fabrika adlarını slot bazlı adlara çevir (elle ad
                # verilmişse dokunma)
                for _ch in range(16):
                    cursor.execute(
                        "UPDATE weidmuller_io_points SET name=? "
                        "WHERE module_id=? AND point_type='DI' "
                        "AND channel=? AND name=?",
                        (f'S1_DI{_ch+1}', _mid, _ch, f'DI{_ch+1}'),
                    )
                    cursor.execute(
                        "UPDATE weidmuller_io_points SET name=? "
                        "WHERE module_id=? AND point_type='DO' "
                        "AND channel=? AND name=?",
                        (f'S3_DO{_ch+1}', _mid, _ch, f'DO{_ch+1}'),
                    )
                # Slot2 DI kanalları (16..31) eksikse ekle
                for _ch in range(16, 32):
                    cursor.execute(
                        '''INSERT OR IGNORE INTO weidmuller_io_points
                           (module_id, point_type, channel, name, unit, scale,
                            offset, is_visible, sort_order, description)
                           VALUES (?, 'DI', ?, ?, '', 1.0, 0.0, 1, ?, '')''',
                        (_mid, _ch, f'S2_DI{_ch-15}', 100 + _ch),
                    )
                _logger.info(
                    "Weidmüller modül #%s v3 haritasına taşındı (32DI+16DO)",
                    _mid,
                )
            cursor.execute(
                "UPDATE system_settings SET setting_value='3' "
                "WHERE setting_key='weidmuller_schema_version'"
            )

        # Seed default module: mevcut oraps_weidmuller_ip ayarını host olarak
        # kullan (yoksa gerçek cihaz IP'si 192.168.0.222). Register haritası
        # ve kanal listesi GERÇEK donanıma göre hardcode edilir:
        # UR20-FBC-MOD-TCP-ECO + Slot1:16DI-P + Slot2:16DI-P + Slot3:16DO-P.
        cursor.execute('SELECT COUNT(*) FROM weidmuller_modules')
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "SELECT setting_value FROM system_settings WHERE setting_key='oraps_weidmuller_ip'"
            )
            _ip_row = cursor.fetchone()
            _seed_host = (_ip_row[0] if _ip_row and _ip_row[0] else '192.168.0.222')
            cursor.execute(
                "SELECT setting_value FROM system_settings WHERE setting_key='oraps_weidmuller_port'"
            )
            _port_row = cursor.fetchone()
            try:
                _seed_port = int(_port_row[0]) if _port_row and _port_row[0] else 502
            except (TypeError, ValueError):
                _seed_port = 502
            cursor.execute(
                '''INSERT INTO weidmuller_modules
                   (name, host, port, unit_id, timeout_sec,
                    output_start, output_count, input_start, input_count,
                    ao_words, do_words, ai_words, di_words, raw_max,
                    poll_ms, is_active, mock_mode, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('IO-1', _seed_host, _seed_port, 255, 2.0,
                 0x0800, 16, 0x0000, 32,
                 0, 1, 0, 2, 27648,
                 500, 1, 0,
                 'UR20-FBC-MOD-TCP-ECO + Slot1:16DI-P + Slot2:16DI-P + Slot3:16DO-P',
                 datetime.now().isoformat()),
            )
            _module_id = cursor.lastrowid

            # 32 DI + 16 DO seed — slot bazlı adlar (S1_/S2_ = DI kartları,
            # S3_ = DO kartı). AI/AO donanımda yok, seed edilmez.
            wm_point_seed = []
            for ch in range(16):
                wm_point_seed.append((_module_id, 'DI', ch, f'S1_DI{ch+1}', '', 1.0, 0.0, 1, 100 + ch, ''))
            for ch in range(16, 32):
                wm_point_seed.append((_module_id, 'DI', ch, f'S2_DI{ch-15}', '', 1.0, 0.0, 1, 100 + ch, ''))
            for ch in range(16):
                wm_point_seed.append((_module_id, 'DO', ch, f'S3_DO{ch+1}', '', 1.0, 0.0, 1, 200 + ch, ''))
            cursor.executemany(
                '''INSERT INTO weidmuller_io_points
                   (module_id, point_type, channel, name, unit, scale, offset,
                    is_visible, sort_order, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                wm_point_seed,
            )

        conn.commit()
        
        # Create default admin user if no users exist
        cursor.execute('SELECT COUNT(*) FROM users')
        if cursor.fetchone()[0] == 0:
            self._create_default_admin(cursor)
            conn.commit()
        
        self.close()
    
    def _create_default_admin(self, cursor):
        """Create default admin user"""
        import bcrypt
        password = "Admin123!"
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now = datetime.now().isoformat()

        cursor.execute('''
            INSERT INTO users (username, password_hash, full_name, role,
                               created_at, created_by, password_changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('admin', password_hash, 'System Administrator', 'Admin',
              now, 'SYSTEM', now))
    
    def _check_and_migrate_users(self):
        """Check if users table needs migration and add columns if missing"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Check columns
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'must_change_password' not in columns:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
                conn.commit()
            except Exception as e:
                _logger.warning("Migration error: %s", e)

        if 'pin' not in columns:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN pin TEXT")
                conn.commit()
            except Exception as e:
                _logger.warning("Migration error (pin): %s", e)

        if 'password_changed_at' not in columns:
            try:
                cursor.execute(
                    "ALTER TABLE users ADD COLUMN password_changed_at TEXT"
                )
                # Mevcut kullanıcılar için başlangıç değeri: created_at.
                # Böylece periyodik şifre değiştirme kontrolü mevcut hesaplarda
                # da anlamlı bir taban zamanla çalışır.
                cursor.execute(
                    "UPDATE users SET password_changed_at = created_at "
                    "WHERE password_changed_at IS NULL"
                )
                conn.commit()
            except Exception as e:
                _logger.warning("Migration error (password_changed_at): %s", e)

        self.close()

    def _check_and_migrate_recipes(self):
        """Check if recipes table needs migration for new parameters"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(recipes)")
        columns = [info[1] for info in cursor.fetchall()]
        
        new_columns = [
            ('p1_pressure', 'INTEGER DEFAULT 500'),
            ('p2_hysteresis', 'INTEGER DEFAULT 50'),
            ('p3_limit', 'INTEGER DEFAULT 100'),
            ('t1_inflation', 'INTEGER DEFAULT 10'),
            ('t2_stabilization', 'INTEGER DEFAULT 10'),
            ('t3_measurement', 'INTEGER DEFAULT 60'),
            ('p8_success_drop', 'INTEGER DEFAULT 200'),
            ('is_active', 'INTEGER DEFAULT 1')
        ]
        
        for col, type_def in new_columns:
            if col not in columns:
                try:
                    cursor.execute(f"ALTER TABLE recipes ADD COLUMN {col} {type_def}")
                except Exception as e:
                    _logger.warning("Recipe migration error %s: %s", col, e)
        
        conn.commit()
        self.close()

    def _check_and_migrate_test_records(self):
        """Add device_id column to test_records if missing"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(test_records)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'device_id' not in columns:
            try:
                cursor.execute("ALTER TABLE test_records ADD COLUMN device_id TEXT")
                conn.commit()
                print("Migration: test_records.device_id column added")
            except Exception as e:
                _logger.warning("Migration error (device_id): %s", e)
        if 'port_number' not in columns:
            try:
                cursor.execute("ALTER TABLE test_records ADD COLUMN port_number INTEGER")
                conn.commit()
                print("Migration: test_records.port_number column added")
            except Exception as e:
                _logger.warning("Migration error (port_number): %s", e)
        self.close()

    def _check_and_migrate_test_batches(self):
        """Faz-6: test_batches'a linked_oraps_batch_id ekle (ORABS↔GLT batch bağlantısı)."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(test_batches)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'linked_oraps_batch_id' not in columns:
            try:
                cursor.execute(
                    "ALTER TABLE test_batches ADD COLUMN linked_oraps_batch_id INTEGER"
                )
                conn.commit()
                print("Migration: test_batches.linked_oraps_batch_id column added")
            except Exception as e:
                _logger.warning("Migration error (linked_oraps_batch_id): %s", e)
        self.close()

    def _check_and_migrate_laf_sensors_position(self):
        """Faz-5: laf_sensors'a overview_x, overview_y ekle (chip drag pozisyonu)."""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(laf_sensors)")
            columns = [info[1] for info in cursor.fetchall()]
        except Exception:
            self.close()
            return
        for col in ('overview_x', 'overview_y'):
            if col not in columns:
                try:
                    cursor.execute(
                        f"ALTER TABLE laf_sensors ADD COLUMN {col} REAL"
                    )
                    conn.commit()
                    print(f"Migration: laf_sensors.{col} column added")
                except Exception as e:
                    _logger.warning("Migration error (laf_sensors.%s): %s", col, e)
        self.close()

    @_synchronized
    def update_laf_sensor_position(self, sensor_id: int,
                                    x_pct: float, y_pct: float) -> bool:
        """LAF sensör chip'inin GLB üzerindeki yüzdelik pozisyonunu kaydet."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE laf_sensors SET overview_x=?, overview_y=? WHERE id=?',
                (float(x_pct), float(y_pct), int(sensor_id))
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_laf_sensor_position error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def update_door_position(self, door_index: int,
                             x: float, y: float, z: float = 0.0) -> bool:
        """Kapı ad etiketinin 3D dünya-ofsetini (centroid'e göre dx,dy,dz)
        kaydet (Faz-5 sprite sürükleme)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE oraps_door_labels SET overview_x=?, overview_y=?, '
                'overview_z=? WHERE door_index=?',
                (float(x), float(y), float(z), int(door_index))
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_door_position error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def update_port_position(self, port_index: int,
                             x: float, y: float, z: float = 0.0) -> bool:
        """Port ad etiketinin 3D dünya-ofsetini kaydet (Faz-5 sprite sürükleme)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE oraps_port_labels SET overview_x=?, overview_y=?, '
                'overview_z=? WHERE port_index=?',
                (float(x), float(y), float(z), int(port_index))
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_port_position error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def update_door_visibility(self, door_index: int, visible: int) -> bool:
        """Kapı chip'inin görünürlüğünü (is_visible) kaydet (Faz-5)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE oraps_door_labels SET is_visible=? WHERE door_index=?',
                (1 if visible else 0, int(door_index))
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_door_visibility error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def update_port_visibility(self, port_index: int, visible: int) -> bool:
        """Port chip'inin görünürlüğünü (is_visible) kaydet (Faz-5)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE oraps_port_labels SET is_visible=? WHERE port_index=?',
                (1 if visible else 0, int(port_index))
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_port_visibility error: {e}")
            return False
        finally:
            self.close()

    # ── Kablosuz IR bariyer sensörleri (barrier_sensors) ───────────────
    @_synchronized
    def list_barrier_sensors(self) -> List[Dict[str, Any]]:
        """Tüm bariyer sensörlerini id sırasıyla döner."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, mac, label, port_index, is_enabled, '
                'last_seen_ts, last_state, last_battery_mv, created_at '
                'FROM barrier_sensors ORDER BY id'
            )
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            print(f"[Database] list_barrier_sensors error: {e}")
            return []
        finally:
            self.close()

    @_synchronized
    def get_barrier_sensor_by_mac(self, mac: str) -> Optional[Dict[str, Any]]:
        """MAC ile bariyer sensörü bul (auto-discover için)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, mac, label, port_index, is_enabled, '
                'last_seen_ts, last_state, last_battery_mv, created_at '
                'FROM barrier_sensors WHERE mac=?',
                (mac.strip().lower(),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"[Database] get_barrier_sensor_by_mac error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def add_barrier_sensor(self, mac: str, label: str = '',
                           port_index: Optional[int] = None) -> Optional[int]:
        """Yeni bariyer sensörü ekle (auto-discover). Duplicate MAC'te None döner."""
        try:
            from datetime import datetime as _dt
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO barrier_sensors '
                '(mac, label, port_index, is_enabled, created_at) '
                'VALUES (?, ?, ?, 1, ?)',
                (mac.strip().lower(), label or '', port_index,
                 _dt.now().isoformat())
            )
            new_id = cursor.lastrowid
            conn.commit()
            return int(new_id) if new_id else None
        except Exception as e:
            print(f"[Database] add_barrier_sensor error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def update_barrier_sensor(self, sensor_id: int, **fields) -> bool:
        """Bariyer sensörü alanlarını güncelle. Kabul edilen alanlar:
        label, port_index, is_enabled, last_seen_ts, last_state, last_battery_mv."""
        allowed = {'label', 'port_index', 'is_enabled',
                   'last_seen_ts', 'last_state', 'last_battery_mv'}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return False
        try:
            conn = self.connect()
            cursor = conn.cursor()
            sets = ', '.join(f"{k}=?" for k in clean)
            vals = list(clean.values()) + [int(sensor_id)]
            cursor.execute(
                f"UPDATE barrier_sensors SET {sets} WHERE id=?", vals
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_barrier_sensor error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def delete_barrier_sensor(self, sensor_id: int) -> bool:
        """Bariyer sensörünü sil (event geçmişi audit_trail'de kalır)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM barrier_sensors WHERE id=?',
                           (int(sensor_id),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] delete_barrier_sensor error: {e}")
            return False
        finally:
            self.close()

    def _check_and_migrate_audit_trail(self):
        """Add category column to audit_trail if missing (Faz-2)"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(audit_trail)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'category' not in columns:
            try:
                cursor.execute(
                    "ALTER TABLE audit_trail ADD COLUMN category TEXT DEFAULT 'SYSTEM'"
                )
                conn.commit()
                _logger.info("Migration: audit_trail.category column added")
            except Exception as e:
                _logger.warning("Migration error (audit category): %s", e)
        self.close()

    @_synchronized
    def get_next_test_sequence(self, device_id: str) -> int:
        """Get next sequential test number for a device.
        Scans test_records for test_id matching '{device_id}-NNNNNNNNN' pattern,
        returns max(N) + 1.  Falls back to 1 if no prior tests exist.
        """
        conn = self.connect()
        cursor = conn.cursor()
        prefix = f"{device_id}-"
        cursor.execute(
            "SELECT test_id FROM test_records WHERE test_id LIKE ?",
            (f"{prefix}%",)
        )
        max_seq = 0
        for row in cursor.fetchall():
            tid = row[0]  # e.g. 'LCC_cAQdzYg0-000000003'
            suffix = tid[len(prefix):]
            try:
                seq = int(suffix)
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                continue
        self.close()
        return max_seq + 1

    def calculate_data_hash(self, data: Dict[str, Any]) -> str:
        """Calculate SHA-256 hash of data for integrity verification"""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()
    
    @_synchronized
    def verify_data_integrity(self, record_id: int, table: str = 'test_records') -> bool:
        """Verify data integrity by comparing stored hash with calculated hash"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute(f'SELECT * FROM {table} WHERE id = ?', (record_id,))
        row = cursor.fetchone()
        self.close()
        
        if not row:
            return False
        
        data = dict(row)
        stored_hash = data.pop('data_hash', None)
        
        if not stored_hash:
            return False
        
        calculated_hash = self.calculate_data_hash(data)
        return stored_hash == calculated_hash
    
    @_synchronized
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by username"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        self.close()
        
        return dict(row) if row else None

    @_synchronized
    def is_duplicate_offline_test(self, device_id: str, test_start_time: str, port_number: int) -> bool:
        """Check if an offline test with same device_id + timestamp + port already exists.
        Prevents re-saving the same test when CLEAR_TEST_HISTORY was lost and
        the slave re-sends its history on the next sync cycle.
        """
        if not device_id or not test_start_time:
            return False
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM test_records WHERE device_id = ? AND test_start_time = ? AND port_number = ?",
            (device_id, test_start_time, port_number)
        )
        count = cursor.fetchone()[0]
        self.close()
        return count > 0

    @_synchronized
    def create_test_record(self, test_data: Dict[str, Any]) -> int:
        """Create a new test record with data integrity hash"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Calculate data hash
        data_hash = self.calculate_data_hash(test_data)
        test_data['data_hash'] = data_hash
        test_data['created_at'] = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO test_records 
            (test_id, operator_id, glove_batch_number, glove_type, test_start_time,
             target_pressure, target_temperature, test_duration, test_status,
             data_json, data_hash, created_at, device_id, port_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            test_data['test_id'],
            test_data['operator_id'],
            test_data['glove_batch_number'],
            test_data['glove_type'],
            test_data['test_start_time'],
            test_data.get('target_pressure'),
            test_data.get('target_temperature'),
            test_data.get('test_duration'),
            test_data['test_status'],
            test_data.get('data_json', '{}'),
            data_hash,
            test_data['created_at'],
            test_data.get('device_id'),
            test_data.get('port_number')
        ))
        
        record_id = cursor.lastrowid
        conn.commit()
        self.close()
        
        return record_id
    
    @_synchronized
    def update_test_record(self, record_id: int, updates: Dict[str, Any]) -> bool:
        """Update test record and recalculate hash"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Get current record
        cursor.execute('SELECT * FROM test_records WHERE id = ?', (record_id,))
        current = dict(cursor.fetchone())
        
        # Apply updates
        current.update(updates)
        current['modified_at'] = datetime.now().isoformat()
        
        # Recalculate hash (exclude hash field itself)
        hash_data = {k: v for k, v in current.items() if k != 'data_hash'}
        new_hash = self.calculate_data_hash(hash_data)
        
        # Update record — use current values as fallback to avoid nulling out fields
        cursor.execute('''
            UPDATE test_records
            SET test_end_time = ?, test_status = ?, test_result = ?,
                data_json = ?, data_hash = ?, modified_at = ?
            WHERE id = ?
        ''', (
            updates.get('test_end_time', current.get('test_end_time')),
            updates.get('test_status', current.get('test_status')),
            updates.get('test_result', current.get('test_result')),
            updates.get('data_json', current.get('data_json')),
            new_hash,
            current['modified_at'],
            record_id
        ))
        
        conn.commit()
        self.close()
        
        return True
    
    @_synchronized
    def get_test_records(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Retrieve test records with optional filtering"""
        conn = self.connect()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM test_records'
        params = []
        
        if filters:
            conditions = []
            if 'test_id' in filters:
                conditions.append('test_id LIKE ?')
                params.append(f"%{filters['test_id']}%")
            if 'operator_id' in filters:
                conditions.append('operator_id = ?')
                params.append(filters['operator_id'])
            if 'date_from' in filters:
                conditions.append('test_start_time >= ?')
                params.append(filters['date_from'])
            if 'date_to' in filters:
                conditions.append('test_start_time <= ?')
                # T23:59:59 ekle: "2026-02-25" -> "2026-02-25T23:59:59"
                # SQLite string karşılaştırmasında bugünün testleri de dahil olsun
                date_to_val = filters['date_to']
                if len(date_to_val) == 10:  # "yyyy-MM-dd" formatı
                    date_to_val += 'T23:59:59'
                params.append(date_to_val)
            if 'test_status_exact' in filters:
                conditions.append('test_status = ?')
                params.append(filters['test_status_exact'])
            
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
        
        query += ' ORDER BY test_start_time DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        self.close()
        
        return [dict(row) for row in rows]

    @_synchronized
    def get_test_record_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single test record by its primary key ID"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM test_records WHERE id = ?', (record_id,))
        row = cursor.fetchone()
        self.close()
        return dict(row) if row else None
    
    @_synchronized
    def add_signature(self, record_type: str, record_id: int, user_id: int, 
                     meaning: str, data_hash: str) -> int:
        """Add electronic signature to a record"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO electronic_signatures
            (record_type, record_id, user_id, signature_meaning, 
             signed_data_hash, signature_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (record_type, record_id, user_id, meaning, data_hash,
              datetime.now().isoformat()))
        
        sig_id = cursor.lastrowid
        conn.commit()
        self.close()
        
        return sig_id
    
    @_synchronized
    def get_signatures_for_record(self, record_type: str, record_id: int) -> List[Dict[str, Any]]:
        """Retrieve signatures for specific record"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT es.*, u.full_name, u.role
            FROM electronic_signatures es
            JOIN users u ON es.user_id = u.id
            WHERE es.record_type = ? AND es.record_id = ?
            ORDER BY es.signature_timestamp ASC
        ''', (record_type, record_id))
        
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    
    @_synchronized
    def create_user(self, username, password, full_name, role, email=None):
        """Create a new user"""
        import bcrypt
        conn = self.connect()
        cursor = conn.cursor()

        try:
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            now = datetime.now().isoformat()

            cursor.execute('''
                INSERT INTO users (username, password_hash, full_name, role, email,
                                   created_at, must_change_password, password_changed_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ''', (username, password_hash, full_name, role, email, now, now))

            user_id = cursor.lastrowid
            conn.commit()
            return True, user_id
        except sqlite3.IntegrityError:
            return False, "Username already exists"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def update_user(self, user_id, updates):
        """Update user details"""
        import bcrypt
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            # Handle password update separately if present
            if 'password' in updates:
                password = updates.pop('password')
                if password:
                    # Eski şifre ile aynı olamaz
                    cursor.execute('SELECT password_hash FROM users WHERE id = ?', (user_id,))
                    row = cursor.fetchone()
                    if row and bcrypt.checkpw(password.encode('utf-8'), row['password_hash'].encode('utf-8')):
                        return False, "Yeni şifre eski şifre ile aynı olamaz."
                    updates['password_hash'] = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    # Şifre değişim tarihini de otomatik yaz (periyodik şifre
                    # kontrolü bu tarihi baz alır). Arık çağrı tarafının bunu
                    # elle set etmesine gerek yok.
                    updates['password_changed_at'] = datetime.now().isoformat()

            if not updates:
                return True, "No changes to save"

            fields = []
            values = []
            for key, value in updates.items():
                fields.append(f"{key} = ?")
                values.append(value)
            
            values.append(user_id)
            
            query = f"UPDATE users SET {', '.join(fields)}, modified_at = ? WHERE id = ?"
            # Inject timestamp before user_id
            values.insert(-1, datetime.now().isoformat())
            
            cursor.execute(query, values)
            conn.commit()
            return True, "User updated successfully"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def get_all_users(self):
        """Get all users"""
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, username, full_name, role, email, is_active, created_at FROM users ORDER BY username')
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    @_synchronized
    def generate_unique_pin(self) -> str:
        """Generate a unique 4-digit PIN (1000-9999) not used by any other user. Never starts with 0."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT pin FROM users WHERE pin IS NOT NULL")
        used_pins = {row[0] for row in cursor.fetchall()}
        self.close()

        available = [f"{i:04d}" for i in range(1000, 10000) if f"{i:04d}" not in used_pins]
        if not available:
            raise RuntimeError("Tüm 4 haneli PIN'ler kullanılmış!")
        return random.choice(available)

    @_synchronized
    def ensure_all_users_have_pins(self):
        """Auto-assign unique PINs to any users that are missing one. Call at app startup."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE pin IS NULL OR pin = ''")
        missing = [row[0] for row in cursor.fetchall()]
        self.close()

        for user_id in missing:
            try:
                new_pin = self.generate_unique_pin()
                self.update_user_pin(user_id, new_pin)
            except Exception as e:
                _logger.error("ensure_all_users_have_pins error for id=%s: %s", user_id, e)

    @_synchronized
    def update_user_pin(self, user_id: int, new_pin: str):
        """Set a specific PIN for a user"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET pin=?, modified_at=? WHERE id=?",
                       (new_pin, datetime.now().isoformat(), user_id))
        conn.commit()
        self.close()

    @_synchronized
    def get_all_users_with_pins(self) -> List[Dict[str, str]]:
        """Return list of {name, pin} for all active users (for ESP32 broadcast)"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT username, pin FROM users WHERE is_active=1 AND pin IS NOT NULL ORDER BY username")
        rows = cursor.fetchall()
        self.close()
        return [{"name": row[0], "pin": row[1]} for row in rows]

    @_synchronized
    def get_user_pin(self, user_id: int) -> Optional[str]:
        """Get the PIN for a specific user"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT pin FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        self.close()
        return row[0] if row else None

    @_synchronized
    def delete_user(self, user_id):
        """Use soft delete (deactivate) instead of hard delete for audit purposes"""
        return self.update_user(user_id, {'is_active': 0})
    
    @_synchronized
    def hard_delete_user(self, user_id):
        """Permanently delete a user from the database"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT username FROM users WHERE id=?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Kullanıcı bulunamadı."
            if row[0] == 'admin':
                return False, "Admin hesabı silinemez."
            
            cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            return True, "Kullanıcı silindi."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            self.close()
    
    # --- Recipe Management ---
    
    @_synchronized
    def create_recipe(self, name, glove_type, **kwargs):
        """Create a new recipe with advanced parameters, handling legacy columns dynamically"""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            # Check for existing name first
            cursor.execute("SELECT id FROM recipes WHERE name = ?", (name,))
            if cursor.fetchone():
                return False, "Bu reçete adı zaten kullanılıyor."

            # Get actual columns
            cursor.execute("PRAGMA table_info(recipes)")
            columns = [info[1] for info in cursor.fetchall()]
            
            data = {
                'name': name,
                'glove_type': glove_type,
                'created_at': datetime.now().isoformat()
            }
            # Add all provided kwargs to data
            data.update(kwargs)
            
            # Map new values to legacy names if they exist and are NOT NULL
            # This ensures backward compatibility with fields like p1_pressure
            if 'p1_pressure' not in data and 'p2' in data: data['p1_pressure'] = data['p2']
            if 'p2_hysteresis' not in data and 'p4' in data: data['p2_hysteresis'] = data['p4']
            if 'p3_limit' not in data and 'p6' in data: data['p3_limit'] = data['p6']
            if 't1_inflation' not in data and 'p1' in data: data['t1_inflation'] = data['p1']
            if 't2_stabilization' not in data and 'p3' in data: data['t2_stabilization'] = data['p3']
            if 't3_measurement' not in data and 'p7' in data: data['t3_measurement'] = data['p7']
            if 'p8_success_drop' not in data and 'p8' in data: data['p8_success_drop'] = data['p8']
            
            # Legacy fallback for old columns (if they exist)
            if 'target_pressure' in columns and 'p1_pressure' in data:
                data['target_pressure'] = data['p1_pressure']
            if 'duration' in columns:
                t1 = data.get('t1_inflation', 0) or 0
                t2 = data.get('t2_stabilization', 0) or 0
                t3 = data.get('t3_measurement', 0) or 0
                data['duration'] = t1 + t2 + t3
            if 'target_temperature' in columns:
                data['target_temperature'] = 25.0  # Default fallback
            
            # Filter data to only include columns that actually exist in the DB
            valid_data = {k: v for k, v in data.items() if k in columns}
            
            fields = ", ".join(valid_data.keys())
            placeholders = ", ".join(["?" for _ in valid_data])
            query = f"INSERT INTO recipes ({fields}) VALUES ({placeholders})"
            
            cursor.execute(query, list(valid_data.values()))
            recipe_id = cursor.lastrowid
            conn.commit()
            return True, recipe_id
            
        except sqlite3.IntegrityError as e:
            err_msg = str(e).lower()
            if "unique" in err_msg or "name" in err_msg:
                return False, "Bu reçete adı zaten kullanılıyor."
            return False, f"Veritabanı kısıtlama hatası: {e}"
        except Exception as e:
            return False, f"Beklenmeyen hata: {e}"
        finally:
            self.close()

    @_synchronized
    def update_recipe(self, recipe_id, updates):
        """Update recipe details"""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            if not updates:
                return True, "No changes"

            # Get actual DB columns to filter out invalid keys
            cursor.execute("PRAGMA table_info(recipes)")
            columns = [info[1] for info in cursor.fetchall()]
            valid_updates = {k: v for k, v in updates.items() if k in columns}

            if not valid_updates:
                return True, "No valid changes"

            fields = []
            values = []
            for key, value in valid_updates.items():
                fields.append(f"{key} = ?")
                values.append(value)
            
            values.append(recipe_id)
            
            query = f"UPDATE recipes SET {', '.join(fields)}, modified_at = ? WHERE id = ?"
            values.insert(-1, datetime.now().isoformat())
            
            cursor.execute(query, values)
            conn.commit()
            return True, "Recipe updated"
        except sqlite3.IntegrityError:
            return False, "Bu reçete adı zaten kullanılıyor."
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def delete_recipe(self, recipe_id):
        """Delete a recipe"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            conn.commit()
            return True, "Recipe deleted"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def get_all_recipes(self):
        """Get all recipes"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recipes ORDER BY name")
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    @_synchronized
    def get_recipe(self, recipe_id):
        """Get a specific recipe by ID"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
        row = cursor.fetchone()
        self.close()
        return dict(row) if row else None

    # --- Layout Management ---

    @_synchronized
    def save_layout_image(self, image_path):
        """Save layout background image path"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            # Singleton table, clear old first or update
            cursor.execute("DELETE FROM layout_settings")
            cursor.execute("INSERT INTO layout_settings (image_path) VALUES (?)", (image_path,))
            conn.commit()
            return True, "Image saved"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def get_layout_image(self):
        """Get layout background image path"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM layout_settings LIMIT 1")
        row = cursor.fetchone()
        self.close()
        return row['image_path'] if row else None

    @_synchronized
    def get_language(self):
        """Get system language (default 'tr')"""
        return self.get_setting('system_language', 'tr')

    @_synchronized
    def set_language(self, lang):
        """Set system language"""
        return self.set_setting('system_language', lang)

    @_synchronized
    def add_glove_port(self, name, x, y, rfid_tag=None, recipe_id=None):
        """Add a new glove port to the layout with full details"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO glove_ports (name, x_pos, y_pos, rfid_tag, recipe_id, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, x, y, rfid_tag, recipe_id, datetime.now().isoformat()))
            port_id = cursor.lastrowid
            conn.commit()
            return True, port_id
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def update_glove_port_position(self, port_id, x, y):
        """Update port position"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE glove_ports SET x_pos=?, y_pos=? WHERE id=?", (x, y, port_id))
            conn.commit()
            return True
        except Exception as e:
            _logger.error("Port update error: %s", e)
            return False
        finally:
            self.close()

    @_synchronized
    def update_glove_port_details(self, port_id, rfid_tag, recipe_id):
        """Update port RFID and Recipe"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE glove_ports SET rfid_tag=?, recipe_id=? WHERE id=?", 
                          (rfid_tag, recipe_id, port_id))
            conn.commit()
            return True, "Updated successfully"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def delete_glove_port(self, port_id):
        """Delete a port"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM glove_ports WHERE id=?", (port_id,))
            conn.commit()
            return True
        except Exception:
            _logger.debug("delete_glove_port failed for id=%s", port_id)
            return False
        finally:
            self.close()

    @_synchronized
    def clear_all_ports(self):
        """Delete all ports and reset RFID sync capability"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            # 1. Delete all ports
            cursor.execute("DELETE FROM glove_ports")
            
            # 2. Reset RFID CRC settings so system re-fetches data
            # We delete any setting starting with crc_rfid_
            cursor.execute("DELETE FROM settings WHERE key LIKE 'crc_rfid_%'")
            
            conn.commit()
            return True, "All ports cleared and sync reset"
        except Exception as e:
            return False, str(e)
        finally:
            self.close()

    @_synchronized
    def get_all_ports(self):
        """Get all glove ports with recipe names"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.*, r.name as recipe_name 
            FROM glove_ports p
            LEFT JOIN recipes r ON p.recipe_id = r.id
        ''')
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    # ═══════════════════════════════════════════════════════════════════
    # AUDIT TRAIL — thread-safe writers used by AuditManager
    # ═══════════════════════════════════════════════════════════════════
    @_synchronized
    def add_audit_entry(self, timestamp: str, user_id: Optional[int], username: str,
                        action_type: str, table_name: Optional[str] = None,
                        record_id: Optional[int] = None, field_name: Optional[str] = None,
                        old_value: Optional[str] = None, new_value: Optional[str] = None,
                        description: str = "", category: str = "SYSTEM") -> None:
        """Single-shot INSERT for an audit_trail row (lock-protected)."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_trail
            (timestamp, user_id, username, action_type, table_name, record_id,
             field_name, old_value, new_value, description, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, user_id, username, action_type, table_name, record_id,
              field_name, old_value, new_value, description, category))
        conn.commit()
        self.close()

    @_synchronized
    def add_system_event(self, timestamp: str, event_type: str, severity: str,
                         message: str, details: str = "") -> None:
        """Single-shot INSERT for a system_events row (lock-protected)."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO system_events
            (timestamp, event_type, severity, message, details)
            VALUES (?, ?, ?, ?, ?)
        ''', (timestamp, event_type, severity, message, details))
        conn.commit()
        self.close()

    @_synchronized
    def query_audit_trail(self, query: str, params: tuple) -> List[Dict[str, Any]]:
        """Run a pre-built audit_trail SELECT under the DB lock.

        Used by AuditManager.get_audit_trail which assembles its own filter
        clause; this wrapper just ensures the connection lifecycle stays
        inside the shared lock.
        """
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    @_synchronized
    def get_audit_logs(self, limit: int = 1000, start_date: str = None, end_date: str = None,
                       categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Retrieve audit logs with optional date and category filtering"""
        conn = self.connect()
        cursor = conn.cursor()
        
        query = "SELECT * FROM audit_trail"
        params = []
        conditions = []
        
        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date)
        
        if end_date:
            # Add time for end of day if only date is provided, assuming ISO format
            if len(end_date) == 10: 
                end_date = f"{end_date}T23:59:59"
            conditions.append("timestamp <= ?")
            params.append(end_date)
        
        if categories:
            placeholders = ','.join(['?'] * len(categories))
            conditions.append(f"category IN ({placeholders})")
            params.extend(categories)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += " ORDER BY timestamp DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]
    @_synchronized
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a system setting value"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = ?", (key,))
        row = cursor.fetchone()
        self.close()
        return row['setting_value'] if row else default

    @_synchronized
    def set_setting(self, key: str, value: Any):
        """Set a system setting value"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO system_settings (setting_key, setting_value) VALUES (?, ?)", 
                      (key, str(value)))
        conn.commit()
        self.close()

    # ═══════════════════════════════════════════════════════════════════
    # BATCH (TOPLU TEST) İŞLEMLERİ
    # ═══════════════════════════════════════════════════════════════════

    @_synchronized
    def get_batch_for_test_time(self, test_start_time: str) -> Optional[str]:
        """Testin başlama zamanına göre hangi batch'e ait olduğunu bulur.
        Kural: test_start_time >= batch.start_time VE batch ACTIVE veya
               test_start_time >= batch.start_time AND test_start_time <= batch.end_time (COMPLETED).
        Batch adını döner, bulamazsa None."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT batch_name FROM test_batches
                WHERE start_time <= ?
                  AND (status = 'ACTIVE' OR (status = 'COMPLETED' AND end_time >= ?))
                ORDER BY start_time DESC LIMIT 1
            ''', (test_start_time, test_start_time))
            row = cursor.fetchone()
            return row['batch_name'] if row else None
        except Exception as e:
            print(f"[Database] get_batch_for_test_time error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def batch_name_exists(self, batch_name: str) -> bool:
        """Verilen isimde batch zaten var mı kontrol eder."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM test_batches WHERE batch_name = ?', (batch_name,))
            return cursor.fetchone()[0] > 0
        except Exception as e:
            print(f"[Database] batch_name_exists error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def create_batch(self, batch_name: str, operator_id: int,
                     linked_oraps_batch_id: Optional[int] = None) -> Optional[int]:
        """Yeni bir batch başlatır, 'ACTIVE' statüsüyle. Batch ID döner.

        linked_oraps_batch_id: ORABS active_batch satirına (singleton id=1)
        bağlanmış birleşik batch için 1; standalone GLT batch için None.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                'INSERT INTO test_batches '
                '(batch_name, operator_id, start_time, status, linked_oraps_batch_id) '
                'VALUES (?, ?, ?, ?, ?)',
                (batch_name, operator_id, now, 'ACTIVE', linked_oraps_batch_id)
            )
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"[Database] create_batch error: {e}")
            if self.conn:
                self.conn.rollback()
            return None
        finally:
            self.close()

    @_synchronized
    def is_oraps_batch_active(self) -> bool:
        """ORABS aktif batch'i (singleton active_batch id=1) running/paused mı?
        GLT batch başlatılırken otomatik bağlama kararı için kullanılır."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM active_batch WHERE id=1")
            row = cursor.fetchone()
            return bool(row and (row[0] or '') in ('running', 'paused'))
        except Exception as e:
            print(f"[Database] is_oraps_batch_active error: {e}")
            return False
        finally:
            self.close()

    @_synchronized
    def find_active_linked_glt_batch(self, linked_oraps_batch_id: int = 1) -> Optional[Dict[str, Any]]:
        """ORABS active_batch (singleton id=1) ile bağlanmış ACTIVE GLT batch'i bul.
        Birden fazla varsa en yenisini döner."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, batch_name, operator_id, start_time, status '
                'FROM test_batches '
                "WHERE linked_oraps_batch_id=? AND status='ACTIVE' "
                'ORDER BY id DESC LIMIT 1',
                (linked_oraps_batch_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"[Database] find_active_linked_glt_batch error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def get_batch_details(self, batch_id: int) -> Optional[Dict[str, Any]]:
        """Batch'i (durumu ne olursa olsun) portlarıyla birlikte döndürür.
        ORABS finish akışı bağlı GLT batch'i bitirirken kullanır — bu metod
        önceden YOKTU: overview try/except ile sessizce portsuz fallback'e
        düşüyor, GLT batch boş port listesiyle kapatılıp rapor boş kalıyordu."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM test_batches WHERE id = ?',
                           (int(batch_id),))
            batch_row = cursor.fetchone()
            if not batch_row:
                return None
            batch = dict(batch_row)
            cursor.execute(
                '''SELECT bp.* FROM batch_ports bp
                   LEFT JOIN test_records tr ON bp.test_record_id = tr.id
                   WHERE bp.batch_id = ?
                   ORDER BY CASE WHEN tr.test_start_time IS NULL THEN 1 ELSE 0 END,
                            tr.test_start_time ASC''',
                (batch['id'],)
            )
            batch['ports'] = [dict(r) for r in cursor.fetchall()]
            return batch
        except Exception as e:
            print(f"[Database] get_batch_details error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def add_ports_to_batch(self, batch_id: int, ports_data: List[Dict[str, Any]]) -> bool:
        """Batch'e portlar ekler.
        ports_data: [{'port_id': int, 'rfid_tag': str}, ...]
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            for p in ports_data:
                cursor.execute(
                    'INSERT INTO batch_ports (batch_id, port_id, rfid_tag, status) VALUES (?, ?, ?, ?)',
                    (batch_id, p['port_id'], p.get('rfid_tag', ''), 'PENDING')
                )
            conn.commit()
            return True
        except Exception as e:
            print(f"[Database] add_ports_to_batch error: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()

    @_synchronized
    def get_active_batch(self) -> Optional[Dict[str, Any]]:
        """Aktif batch'i ve portlarını döndürür. Yoksa None."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM test_batches WHERE status = ? ORDER BY id DESC LIMIT 1', ('ACTIVE',))
            batch_row = cursor.fetchone()
            if not batch_row:
                return None
            batch = dict(batch_row)
            cursor.execute(
                '''SELECT bp.* FROM batch_ports bp
                   LEFT JOIN test_records tr ON bp.test_record_id = tr.id
                   WHERE bp.batch_id = ?
                   ORDER BY CASE WHEN tr.test_start_time IS NULL THEN 1 ELSE 0 END,
                            tr.test_start_time ASC''',
                (batch['id'],)
            )
            batch['ports'] = [dict(r) for r in cursor.fetchall()]
            return batch
        except Exception as e:
            print(f"[Database] get_active_batch error: {e}")
            return None
        finally:
            self.close()

    @_synchronized
    def update_batch_port_explanation(self, batch_id: int, port_id: int, explanation: str) -> bool:
        """Batch içindeki bir portun açıklamasını port_id ile günceller."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE batch_ports SET explanation = ? WHERE batch_id = ? AND port_id = ?',
                (explanation, batch_id, port_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_batch_port_explanation error: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()

    @_synchronized
    def update_batch_port_status(self, batch_id: int, rfid_tag: str, status: str,
                                  test_record_id: int = None, explanation: str = None) -> bool:
        """Batch içindeki bir portun durumunu günceller.
        Yeni testin test_start_time'ı mevcut testten eskiyse güncelleme yapılmaz.
        RFID eşleşmesi NORMALİZE edilerek yapılır ('0x00DA0DAE' == 'DA0DAE')."""
        try:
            conn = self.connect()
            cursor = conn.cursor()

            # Satırı normalize RFID ile bul (birebir metin eşleşmesi cihaz/PC
            # format farkında boşa düşüyordu).
            want = normalize_rfid(rfid_tag)
            cursor.execute(
                'SELECT id, rfid_tag, test_record_id FROM batch_ports '
                'WHERE batch_id = ?', (batch_id,)
            )
            target = None
            for r in cursor.fetchall():
                if normalize_rfid(r['rfid_tag']) == want:
                    target = dict(r)
                    break
            if target is None:
                print(f"[Database] update_batch_port_status: RFID eşleşmedi "
                      f"(batch={batch_id}, rfid={rfid_tag!r})")
                return False

            if target.get('test_record_id') and test_record_id:
                # Mevcut ve yeni testin zamanlarını karşılaştır
                cursor.execute(
                    'SELECT test_start_time FROM test_records WHERE id = ?',
                    (target['test_record_id'],)
                )
                existing = cursor.fetchone()
                cursor.execute(
                    'SELECT test_start_time FROM test_records WHERE id = ?',
                    (test_record_id,)
                )
                incoming = cursor.fetchone()
                if existing and incoming and existing[0] and incoming[0]:
                    if incoming[0] < existing[0]:
                        print(f"[Database] Eski test atlandı: gelen={incoming[0]} < mevcut={existing[0]}")
                        return False

            cursor.execute(
                '''UPDATE batch_ports
                   SET status = ?, test_record_id = COALESCE(?, test_record_id), explanation = COALESCE(?, explanation)
                   WHERE id = ?''',
                (status, test_record_id, explanation, target['id'])
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] update_batch_port_status error: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()

    @_synchronized
    def complete_batch(self, batch_id: int) -> bool:
        """Batch'i tamamlar: status='COMPLETED', end_time atar."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                'UPDATE test_batches SET status = ?, end_time = ? WHERE id = ?',
                ('COMPLETED', now, batch_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"[Database] complete_batch error: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()

    # ═══════════════════════════════════════════════════════════════════
    # BATCH ŞABLONLARI
    # ═══════════════════════════════════════════════════════════════════

    @_synchronized
    def save_batch_template(self, template_name: str, port_ids: List[int], user_id: int) -> Optional[int]:
        """Yeni batch şablonu kaydet. Template ID döner."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                'INSERT INTO batch_templates (template_name, created_by, created_at) VALUES (?, ?, ?)',
                (template_name, user_id, now)
            )
            template_id = cursor.lastrowid
            for pid in port_ids:
                cursor.execute(
                    'INSERT INTO batch_template_ports (template_id, port_id) VALUES (?, ?)',
                    (template_id, pid)
                )
            conn.commit()
            return template_id
        except Exception as e:
            print(f"[Database] save_batch_template error: {e}")
            if self.conn:
                self.conn.rollback()
            return None
        finally:
            self.close()

    @_synchronized
    def get_batch_templates(self) -> List[Dict[str, Any]]:
        """Tüm batch şablonlarını port sayılarıyla birlikte döner."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT bt.id, bt.template_name, bt.created_at, bt.created_by,
                       COUNT(btp.id) as port_count
                FROM batch_templates bt
                LEFT JOIN batch_template_ports btp ON bt.id = btp.template_id
                GROUP BY bt.id
                ORDER BY bt.template_name
            ''')
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            print(f"[Database] get_batch_templates error: {e}")
            return []
        finally:
            self.close()

    @_synchronized
    def get_template_ports(self, template_id: int) -> List[int]:
        """Şablondaki port ID'lerini döner."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT port_id FROM batch_template_ports WHERE template_id = ?',
                (template_id,)
            )
            return [r['port_id'] for r in cursor.fetchall()]
        except Exception as e:
            print(f"[Database] get_template_ports error: {e}")
            return []
        finally:
            self.close()

    @_synchronized
    def delete_batch_template(self, template_id: int) -> bool:
        """Batch şablonunu sil (portlar da silinir)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM batch_template_ports WHERE template_id = ?', (template_id,))
            cursor.execute('DELETE FROM batch_templates WHERE id = ?', (template_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"[Database] delete_batch_template error: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()

    @_synchronized
    def batch_template_name_exists(self, name: str) -> bool:
        """Verilen isimde şablon var mı kontrol eder."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM batch_templates WHERE template_name = ?', (name,))
            return cursor.fetchone()[0] > 0
        except Exception as e:
            print(f"[Database] batch_template_name_exists error: {e}")
            return False
        finally:
            self.close()
