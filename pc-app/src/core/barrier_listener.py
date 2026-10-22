"""Kablosuz IR bariyer sensör dinleyicisi (Faz-7, 2026-07-06).

Master ESP32-S3 (USB CDC) → PC seri portu → BarrierListener QThread → parse →
sinyal → BarrierManager (ana thread) → oraps port motion event + audit +
3D viewer mavi boyama.

Master mesaj formatı (bkz. bariyer/HardwareSoftware/Hardware/main/master.c):

    >>> [aa:bb:cc:dd:ee:ff] MESAJ: <payload> <<<

Payload'lar (slave.c):
    E1                    → bariyer bloke oldu (engel var / hareket)
    E0                    → bariyer serbest kaldı
    HB c=NNN              → heartbeat (2 dk aralık)
    HB c=NNN V=X.YY       → heartbeat + pil voltajı (saatte 1)

Threading:
    - Listener QThread'de çalışır (serial blocking read).
    - `barrier_event(mac, event, dict)` sinyali GUI thread'e queue'lanır.
    - DB yazımı ana thread'de BarrierManager tarafından yapılır (thread-safe
      DB lock zaten mevcut).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal, QObject

# Serial import lazy — bağımlılık eksikse listener sessizce devre dışı kalır.
try:
    import serial
    from serial.tools import list_ports as _list_ports
    _HAS_SERIAL = True
except Exception:  # pragma: no cover
    serial = None  # type: ignore
    _list_ports = None  # type: ignore
    _HAS_SERIAL = False


# Master log satırı regex — master.c'deki ESP_LOGW format:
#   ">>> [xx:xx:xx:xx:xx:xx] MESAJ: <payload> <<<"
_MSG_RE = re.compile(
    r'>>>\s*\[([0-9a-fA-F:]{17})\]\s*MESAJ:\s*(.+?)\s*<<<'
)

# Heartbeat payload — "HB c=42" ya da "HB c=42 V=3.85"
_HB_RE = re.compile(
    r'^HB\s+c=(\d+)(?:\s+V=(\d+(?:\.\d+)?))?\s*$'
)


class BarrierListener(QThread):
    """Master COM'undan bariyer mesajlarını dinleyen thread.

    Kullanım (ana thread):
        listener = BarrierListener()
        listener.barrier_event.connect(manager.handle_event)
        listener.set_port('COM7')   # veya '' → auto-discover
        listener.start()
        ...
        listener.stop(); listener.wait()
    """

    # (mac_lower, event, payload_dict) — event: 'BROKEN'|'CLEARED'|'HEARTBEAT'
    barrier_event = pyqtSignal(str, str, dict)
    # (connected, port_name_or_message)
    connection_status = pyqtSignal(bool, str)
    # Raw log line (debug)
    raw_line = pyqtSignal(str)

    # Master USB CDC descriptor eşleşme adayları:
    #   • description/product alanları için: "LCC Bariyer Master"
    #   • hwid alanı için: VID:PID (Espressif ESP32-S3 native USB CDC =
    #     303A:4B43) ve iUSB serial "BARIYER-MASTER-..."
    # Windows generic CDC sürücüsü description alanına sadece
    # "USB Serial Device (COMxx)" yazdığı için hwid'e bakmadan bulmak
    # mümkün değildi (Faz-8 fix).
    _CDC_DESCRIPTOR_MATCH = ('lcc bariyer master', 'bariyer master')
    _HWID_MATCH = ('303a:4b43', 'bariyer-master')

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._stop = False
        self._port: str = ''       # boş → auto-discover
        self._baud = 115200
        self._ser = None

    # ── Config ──────────────────────────────────────────────────
    def set_port(self, port_name: str):
        """COM portunu ayarla. Boş string → auto-discover."""
        self._port = (port_name or '').strip()

    def stop(self):
        self._stop = True

    # ── Auto-discover ───────────────────────────────────────────
    def _autodiscover(self) -> Optional[str]:
        """Master COM portunu USB descriptor/hwid alanlarından bul.

        Öncelik:
          1. description/product içinde "LCC Bariyer Master" ifadesi.
          2. hwid içinde VID:PID `303A:4B43` (Espressif ESP32-S3 native USB
             CDC) veya serial number "BARIYER-MASTER-...".
        """
        if not _HAS_SERIAL or _list_ports is None:
            return None
        try:
            ports = list(_list_ports.comports())
        except Exception:
            return None
        # 1) description/product eşleşmesi
        for p in ports:
            desc = (getattr(p, 'description', '') or '').lower()
            product = (getattr(p, 'product', '') or '').lower()
            hay = f"{desc} {product}"
            for needle in self._CDC_DESCRIPTOR_MATCH:
                if needle in hay:
                    return p.device
        # 2) hwid (VID:PID / iSerial) eşleşmesi — Windows generic CDC
        # sürücüsünde description bilgisi kaybolduğu için fallback.
        for p in ports:
            hwid = (getattr(p, 'hwid', '') or '').lower()
            if not hwid:
                continue
            for needle in self._HWID_MATCH:
                if needle in hwid:
                    return p.device
        return None

    def _resolve_port(self) -> Optional[str]:
        if self._port:
            return self._port
        return self._autodiscover()

    # ── Parser ──────────────────────────────────────────────────
    def _parse_line(self, line: str):
        """Bir satırı parse et; geçerliyse sinyal yay."""
        line = (line or '').strip()
        if not line:
            return
        try:
            self.raw_line.emit(line)
        except Exception:
            pass
        m = _MSG_RE.search(line)
        if not m:
            return   # başka log satırı (ESP_LOGI/D vs.)
        mac = m.group(1).strip().lower()
        payload = m.group(2).strip()
        # Payload → event tipi
        if payload == 'E1':
            self.barrier_event.emit(mac, 'BROKEN',
                                    {'raw': payload,
                                     'ts': datetime.now().isoformat(timespec='seconds')})
            return
        if payload == 'E0':
            self.barrier_event.emit(mac, 'CLEARED',
                                    {'raw': payload,
                                     'ts': datetime.now().isoformat(timespec='seconds')})
            return
        hb = _HB_RE.match(payload)
        if hb:
            info = {
                'raw': payload,
                'ts': datetime.now().isoformat(timespec='seconds'),
                'counter': int(hb.group(1)),
            }
            if hb.group(2):
                try:
                    info['battery_mv'] = int(round(float(hb.group(2)) * 1000))
                except (TypeError, ValueError):
                    pass
            self.barrier_event.emit(mac, 'HEARTBEAT', info)

    # ── Main loop ───────────────────────────────────────────────
    def run(self):
        if not _HAS_SERIAL:
            self.connection_status.emit(
                False, "pyserial yok — bariyer dinleyici devre dışı"
            )
            return
        while not self._stop:
            port = self._resolve_port()
            if not port:
                self.connection_status.emit(
                    False, "Bariyer master COM portu bulunamadı"
                )
                # 3 sn bekle + retry (kablo takılırsa yakalasın)
                for _ in range(30):
                    if self._stop:
                        return
                    self.msleep(100)
                continue
            try:
                self._ser = serial.Serial(port, self._baud, timeout=0.5)
            except Exception as e:
                self.connection_status.emit(False, f"{port} açılamadı: {e}")
                for _ in range(30):
                    if self._stop:
                        return
                    self.msleep(100)
                continue
            self.connection_status.emit(True, port)
            try:
                while not self._stop:
                    try:
                        raw = self._ser.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    try:
                        line = raw.decode('utf-8', errors='replace')
                    except Exception:
                        continue
                    self._parse_line(line)
            finally:
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self.connection_status.emit(False, "Bağlantı koptu")
            # Kısa bekle ve tekrar dene
            for _ in range(20):
                if self._stop:
                    return
                self.msleep(100)


class BarrierManager(QObject):
    """Bariyer sensör event'lerini işleyip DB'ye ve ORABS port motion
    sistemine bağlar. Ana thread'de çalışır (BarrierListener sinyallerini
    QueuedConnection ile alır).

    Ayrıca son N saniye içinde `BROKEN` olan sensörleri ve pil durumunu
    izlenmek üzere hafızada tutar (UI'da anlık gösterge için).
    """

    # (port_index, is_broken) — 3D viewer motion boyaması için (5sn hold ile)
    port_motion_from_barrier = pyqtSignal(int, bool)
    # (mac_lower, sensor_id_or_none) — yeni bir bariyer otomatik eklendi
    sensor_discovered = pyqtSignal(str, object)
    # Genel refresh (UI listesi için)
    sensors_changed = pyqtSignal()
    # Pairing mode: kullanıcı bir bariyeri fiziksel test ile tanıtırken
    # BROKEN event geldiğinde yayınlanır. (mac, sensor_id_or_None)
    # Overview 'Eşleme Modu' listener'ı bu sinyalle porta bağlar.
    pairing_candidate = pyqtSignal(str, object)

    def __init__(self, database, batch_manager, audit_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.bm = batch_manager
        self.audit = audit_manager
        # mac_lower → sensor row (last known)
        self._cache: dict = {}
        self._low_battery_alarmed: set = set()
        # Pairing mode: aktifken E1 (BROKEN) gelirse `pairing_candidate`
        # sinyali de yayınlanır (normal port motion event yine akmaya devam
        # eder). Overview eşleme mod handler'ı bu sinyalle porta bağlar.
        self._pairing_mode: bool = False
        try:
            self._low_battery_mv = int(
                self.db.get_setting('barrier_low_battery_mv', '3200') or '3200'
            )
        except Exception:
            self._low_battery_mv = 3200

    # ── Pairing mode ────────────────────────────────────────────
    def set_pairing_mode(self, enabled: bool):
        """Fiziksel test ile bariyer-port eşleme modunu aç/kapa.
        Aktifken bir sensör BROKEN (E1) gönderirse `pairing_candidate`
        sinyali yayınlanır."""
        self._pairing_mode = bool(enabled)

    def is_pairing_mode(self) -> bool:
        return self._pairing_mode

    # ── Public API ──────────────────────────────────────────────
    def handle_event(self, mac: str, event: str, info: dict):
        """BarrierListener.barrier_event → ana thread slot'u.
        Auto-discover: bilinmeyen MAC gelirse yeni sensör olarak ekle."""
        mac = (mac or '').strip().lower()
        if not mac:
            return
        sensor = self._get_or_create(mac)
        if sensor is None:
            return
        sid = int(sensor.get('id') or 0)
        pidx = sensor.get('port_index')
        if pidx is not None:
            try:
                pidx = int(pidx)
            except (TypeError, ValueError):
                pidx = None
        now_iso = info.get('ts') or datetime.now().isoformat(timespec='seconds')

        if event == 'BROKEN':
            self._update_sensor(sid, last_seen_ts=now_iso, last_state='BROKEN')
            if pidx is not None:
                # ORABS port motion event → 3D mavi + audit (mevcut sistem)
                try:
                    self.bm.log_port_motion_event(pidx, detected=True, source='BARRIER')
                except Exception:
                    import traceback; traceback.print_exc()
                self.port_motion_from_barrier.emit(pidx, True)
            # Pairing mode aktifse: bu sensörü eşleme adayı olarak yayınla.
            if self._pairing_mode:
                try:
                    self.pairing_candidate.emit(mac, sid)
                except Exception:
                    pass
        elif event == 'CLEARED':
            self._update_sensor(sid, last_seen_ts=now_iso, last_state='IDLE')
            if pidx is not None:
                try:
                    self.bm.log_port_motion_event(pidx, detected=False, source='BARRIER')
                except Exception:
                    import traceback; traceback.print_exc()
                self.port_motion_from_barrier.emit(pidx, False)
        elif event == 'HEARTBEAT':
            fields = {'last_seen_ts': now_iso}
            bmv = info.get('battery_mv')
            if bmv is not None:
                fields['last_battery_mv'] = int(bmv)
                # Düşük pil audit — MAC başına bir kez uyar (batarya>eşik olunca reset)
                if int(bmv) < self._low_battery_mv:
                    if mac not in self._low_battery_alarmed:
                        self._low_battery_alarmed.add(mac)
                        try:
                            if self.audit is not None:
                                self.audit.log_action(
                                    action_type='BARRIER_LOW_BATTERY',
                                    table_name='barrier_sensors',
                                    record_id=sid,
                                    description=(
                                        f"Bariyer '{sensor.get('label') or ('#'+str(sid))}' "
                                        f"pil düşük: {bmv/1000:.2f} V"
                                    ),
                                    new_value=str(bmv),
                                    category='ORAPS',
                                )
                        except Exception:
                            import traceback; traceback.print_exc()
                else:
                    self._low_battery_alarmed.discard(mac)
            self._update_sensor(sid, **fields)

    def refresh_settings(self):
        """Ayarlar değişince (barrier_low_battery_mv vs.) çağrılır."""
        try:
            self._low_battery_mv = int(
                self.db.get_setting('barrier_low_battery_mv', '3200') or '3200'
            )
        except Exception:
            pass

    # ── Internal ────────────────────────────────────────────────
    def _get_or_create(self, mac: str) -> Optional[dict]:
        # Cache stale olabilir: kullanıcı UI'dan port_index/label değiştirince
        # DB güncellenir ama BarrierManager'da yaşayan cache bunu görmez ve
        # sonraki BROKEN event pidx=None ile geçip motion event yayınlanmaz
        # (Faz-8 bug). Bu yüzden HER çağrıda DB'den taze row çekiyoruz;
        # cache sadece "auto-discovery gerekli mi" hızlı kararı için tutulur.
        try:
            row = self.db.get_barrier_sensor_by_mac(mac)
        except Exception:
            row = None
        if row is None:
            # Auto-discover: yeni bariyer olarak ekle
            try:
                # Etiket: mevcut sayı + 1
                existing = self.db.list_barrier_sensors() or []
                default_label = f"Bariyer #{len(existing) + 1}"
                new_id = self.db.add_barrier_sensor(mac, label=default_label)
            except Exception:
                import traceback; traceback.print_exc()
                new_id = None
            if new_id:
                try:
                    if self.audit is not None:
                        self.audit.log_action(
                            action_type='BARRIER_DISCOVERED',
                            table_name='barrier_sensors',
                            record_id=int(new_id),
                            description=f"Yeni bariyer sensörü tespit edildi (MAC {mac})",
                            new_value=mac,
                            category='ORAPS',
                        )
                except Exception:
                    pass
                row = self.db.get_barrier_sensor_by_mac(mac)
                try:
                    self.sensor_discovered.emit(mac, int(new_id))
                    self.sensors_changed.emit()
                except Exception:
                    pass
        if row:
            self._cache[mac] = row
        return row

    def _update_sensor(self, sid: int, **fields):
        try:
            self.db.update_barrier_sensor(int(sid), **fields)
        except Exception:
            import traceback; traceback.print_exc()
            return
        # Cache'i de tazele
        for mac, row in list(self._cache.items()):
            if int(row.get('id') or 0) == int(sid):
                row.update(fields)
                break
