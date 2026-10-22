"""
LAF Modbus polling worker (Faz-5)
==================================
QThread that polls the clean-room monitor board over a USB→Modbus RTU
adapter and emits live sensor readings + alarm events.

Threading rules (Plan B):
- Worker NEVER writes to the DB directly. It emits signals only.
- The LAF panel runs in the GUI thread, receives `readings_updated`
  and forwards snapshots to LafManager.add_snapshot() every snapshot_sec.

NOT: Mock mod tamamen kaldırıldı. Worker daima Modbus RTU dener; port
açılamıyorsa "Modbus bekleniyor" statüsü emit eder ve arka planda tekrar
denemeye devam eder. Sensor değerleri okunamadığında None yayınır.
"""

from __future__ import annotations

import struct
import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal


class LafWorker(QThread):
    # {sensor_id: value|None}, timestamp_iso
    readings_updated = pyqtSignal(dict, str)
    # flag_code, message
    alarm_received = pyqtSignal(str, str)
    # connected (bool), message
    connection_status = pyqtSignal(bool, str)

    def __init__(self, laf_manager, parent=None):
        super().__init__(parent)
        self.laf = laf_manager
        self._stop = False
        self._client = None
        self._sensors: List[Dict] = []
        self._cfg: Dict[str, str] = {}
        self._poll_sec = 5.0
        self._last_error = ''
        self._last_status = None

    # ── Lifecycle ────────────────────────────────────────────────
    def stop(self):
        self._stop = True

    def reload_config(self):
        """Re-read sensors + settings from DB. Safe to call from GUI thread
        ONLY while the worker is stopped, or via a queued signal connection."""
        self._sensors = self.laf.list_sensors(only_visible=False)
        self._cfg = self.laf.get_settings()
        try:
            self._poll_sec = max(1.0, float(self._cfg.get('laf_poll_sec', '5')))
        except (TypeError, ValueError):
            self._poll_sec = 5.0

    # ── Main loop ────────────────────────────────────────────────
    def run(self):
        self.reload_config()

        ok = self._open_modbus()
        if not ok:
            self._emit_status(False, f"Modbus bekleniyor: {self._last_error or 'bağlantı kurulamadı'}")
        else:
            self._emit_status(True, f"Modbus bağlı: {self._cfg.get('laf_com_port', '?')}")

        while not self._stop:
            readings = self._poll_once()
            ts = datetime.now().isoformat()
            self.readings_updated.emit(readings, ts)

            # Sleep in small chunks so stop() takes effect quickly
            elapsed = 0.0
            while elapsed < self._poll_sec and not self._stop:
                time.sleep(0.1)
                elapsed += 0.1

        self._close_modbus()

    # ── Polling ──────────────────────────────────────────────────
    def _poll_once(self) -> Dict[int, Optional[float]]:
        out: Dict[int, Optional[float]] = {}
        if self._client is None:
            if self._open_modbus():
                self._emit_status(True, f"Modbus bağlı: {self._cfg.get('laf_com_port', '?')}")
            else:
                self._emit_status(False, f"Modbus bekleniyor: {self._last_error or 'bağlantı kurulamadı'}")
                return {s['id']: None for s in self._sensors}

        slave = int(self._cfg.get('laf_slave_id', '1'))
        success_count = 0
        for s in self._sensors:
            try:
                raw = self._read_register(s, slave)
                if raw is None:
                    out[s['id']] = None
                else:
                    out[s['id']] = raw * float(s['scale']) + float(s['offset'])
                    success_count += 1
            except Exception as exc:
                self._last_error = str(exc)
                out[s['id']] = None
        if success_count:
            self._emit_status(True, f"Modbus bağlı: {self._cfg.get('laf_com_port', '?')}")
        elif self._sensors:
            self._close_modbus()
            self._emit_status(False, f"Modbus okuma yok, tekrar denenecek: {self._last_error or 'cevap yok'}")
        return out

    # ── Modbus helpers ───────────────────────────────────────────
    def _open_modbus(self) -> bool:
        try:
            from pymodbus.client import ModbusSerialClient  # type: ignore
        except Exception as exc:
            self._last_error = f"pymodbus yüklenemedi: {exc}"
            return False
        port = self._cfg.get('laf_com_port', '').strip()
        if not port:
            self._last_error = "COM portu boş"
            return False
        try:
            self._client = ModbusSerialClient(
                port=port,
                baudrate=int(self._cfg.get('laf_baud', '19200')),
                parity=self._cfg.get('laf_parity', 'N') or 'N',
                stopbits=int(self._cfg.get('laf_stop_bits', '1')),
                bytesize=8,
                timeout=1.0,
            )
            ok = bool(self._client.connect())
            if not ok:
                self._last_error = f"{port} açılamadı"
                self._close_modbus()
            return ok
        except Exception as exc:
            self._last_error = str(exc)
            self._client = None
            return False

    def _emit_status(self, ok: bool, message: str):
        status = (ok, message)
        if status != self._last_status:
            self._last_status = status
            self.connection_status.emit(ok, message)

    def _close_modbus(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _read_register(self, sensor: Dict, slave: int) -> Optional[float]:
        addr = int(sensor['register_addr'])
        rtype = sensor['register_type']
        dtype = sensor['data_type']
        word_count = 2 if dtype in ('uint32', 'int32', 'float32') else 1

        if rtype == 'input':
            rr = self._client.read_input_registers(addr, count=word_count, slave=slave)
        else:
            rr = self._client.read_holding_registers(addr, count=word_count, slave=slave)
        if rr.isError():
            return None
        regs = rr.registers
        if dtype == 'uint16':
            return float(regs[0])
        if dtype == 'int16':
            v = regs[0]
            return float(v - 0x10000 if v & 0x8000 else v)
        # 32-bit: big-endian word order
        raw = struct.pack('>HH', regs[0], regs[1])
        if dtype == 'uint32':
            return float(struct.unpack('>I', raw)[0])
        if dtype == 'int32':
            return float(struct.unpack('>i', raw)[0])
        if dtype == 'float32':
            return float(struct.unpack('>f', raw)[0])
        return None
