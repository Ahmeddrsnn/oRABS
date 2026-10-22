"""
Weidmüller IO polling worker (Faz-6a)
======================================
QThread that polls a Weidmüller UR20-FBC-MOD-TCP coupler over Modbus TCP
and emits live IO values + connection status. Supports DO/AO writes via a
thread-safe command queue (Plan B: GUI thread queues, worker executes).

Hardware notes (UR20-FBC-MOD-TCP):
- Coupler does NOT support Coil/Discrete Input function codes.
- Process Input  (DI+AI) lives in holding registers @ 0x0000 ...
- Process Output (DO+AO) lives in holding registers @ 0x0800 ...
- Coupler identity ASCII string @ 0x1000 (8 regs, word-swap, low byte first).
- Analog raw scale: 0..27648 ↔ 0..100 % (0..10 V / 4..20 mA).

Threading rules (Plan B):
- Worker NEVER writes to the DB directly. It emits signals only.
- The IO panel runs in the GUI thread and forwards audit events to
  WeidmullerManager.log_write() upon receiving `write_completed`.

NOT: Mock mod tamamen kaldırıldı. Worker daima gerçek Modbus TCP dener;
bağlantı kurulamazsa "Modbus TCP bağlantısı kurulamadı — bekleniyor"
statüsü emit eder ve arka planda reconnect denemeye devam eder.
"""

from __future__ import annotations

import queue
import struct
import time
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal


def _regs_to_bits(regs):
    """16-bit register list → bit list (LSB-first per register)."""
    bits = []
    for reg in regs:
        for i in range(16):
            bits.append((reg >> i) & 1)
    return bits


def _raw_to_signed16(raw: int) -> int:
    return struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]


def raw_to_percent(raw: int, raw_max: int = 27648) -> float:
    return _raw_to_signed16(raw) * 100.0 / raw_max


def percent_to_raw(pct: float, raw_max: int = 27648) -> int:
    pct = max(-100.0, min(100.0, pct))
    raw = int(round(pct * raw_max / 100.0))
    if raw < 0:
        raw = (raw + 0x10000) & 0xFFFF
    return raw & 0xFFFF


class WeidmullerWorker(QThread):
    # module_id, values dict {'DI': {ch:bit}, 'DO': {ch:bit},
    #                         'AI': {ch:{raw,pct}}, 'AO': {ch:{raw,pct}}}, ts_iso
    registers_updated = pyqtSignal(int, dict, str)
    # module_id, connected, message
    connection_status = pyqtSignal(int, bool, str)
    # module_id, coupler_id_ascii
    coupler_identified = pyqtSignal(int, str)
    # module_id, point_type, channel, value, success, error_msg
    write_completed = pyqtSignal(int, str, int, object, bool, str)
    # module_id, channel, new_state(0|1), ts_iso  — edge-only
    di_edge = pyqtSignal(int, int, int, str)
    # Faz-6g: AI alıcı eşik aşımı (yeni durum).
    # module_id, channel, severity('HIGH'|'LOW'|'OK'), value_eng, threshold, ts_iso
    ai_alarm = pyqtSignal(int, int, str, float, float, str)

    def __init__(self, weidmuller_manager, module_id: int, parent=None):
        super().__init__(parent)
        self.wm = weidmuller_manager
        self.module_id = module_id
        self._stop = False
        self._client = None
        self._cfg: Dict = {}
        self._cmd_q: "queue.Queue[dict]" = queue.Queue()
        self._poll_sec = 0.5
        # Previous DI snapshot for edge detection (channel -> 0/1).
        # None until the first successful poll, so we don't fire spurious
        # edges from the initial transition.
        self._prev_di: Optional[Dict[int, int]] = None
        # Faz-6d-4: per-channel debounce. Stores last accepted edge time
        # (monotonic). Edges that arrive within `_debounce_sec` of the
        # last accepted one for the same channel are dropped.
        self._last_edge_t: Dict[int, float] = {}
        self._debounce_sec = 0.1  # default 100 ms, overridden in reload_config
        # Faz-6g: AI alarm state per channel. 'OK' | 'HIGH' | 'LOW'.
        # Reload_config refreshes thresholds from DB.
        self._ai_alarm_state: Dict[int, str] = {}
        self._ai_thresholds: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
        self._ai_scale: Dict[int, Tuple[float, float]] = {}  # ch -> (scale, offset)
        # Faz-6f: last connection_status snapshot. View'lar geç attach
        # olduğunda (start_all → attach_workers_from_bridge sırasındaki
        # mikro-pencerede emit edilen ilk durumu kaçırabilirler) bu
        # değeri kendileri okuyup status_lbl'i hizalar.
        self._last_conn_connected: Optional[bool] = None
        self._last_conn_message: str = ""
        self._last_coupler: str = ""

    # ── Lifecycle ────────────────────────────────────────────────
    def stop(self):
        self._stop = True

    # ── Connection snapshot helpers (Faz-6f) ─────────────────────
    def _emit_conn(self, ok: bool, msg: str):
        """Tek noktadan connection_status emit; son durum saklanır ki
        geç bağlanan view'lar `last_connection()` ile hizalanabilsin."""
        self._last_conn_connected = bool(ok)
        self._last_conn_message = str(msg)
        self.connection_status.emit(self.module_id, bool(ok), str(msg))

    def _emit_coupler(self, name: str):
        self._last_coupler = str(name or '')
        if name:
            self.coupler_identified.emit(self.module_id, str(name))

    def last_connection(self) -> Optional[Tuple[bool, str]]:
        """Son bağlantı durumunu döndür (henüz emit edilmemişse None).
        View attach anında çağrılarak status_lbl'i hemen senkronlamak
        için kullanılır."""
        if self._last_conn_connected is None:
            return None
        return (self._last_conn_connected, self._last_conn_message)

    def last_coupler(self) -> str:
        return self._last_coupler

    def reload_config(self):
        """Re-read module config from DB. Call from GUI thread while stopped."""
        mod = self.wm.get_module(self.module_id)
        if not mod:
            return
        self._cfg = mod
        try:
            self._poll_sec = max(0.001, int(mod.get('poll_ms', 500)) / 1000.0)
        except (TypeError, ValueError):
            self._poll_sec = 0.5
        # Global debounce (system_settings.oraps_di_debounce_ms); 0 disables.
        try:
            ms = int(self.wm.db.get_setting('oraps_di_debounce_ms', '100'))
        except (TypeError, ValueError):
            ms = 100
        self._debounce_sec = max(0.0, ms / 1000.0)
        # AI alarm eşikleri & ölçek: list_points'tan yenile.
        self._ai_thresholds.clear()
        self._ai_scale.clear()
        try:
            for p in self.wm.list_points(module_id=self.module_id,
                                          point_type='AI'):
                ch = int(p['channel'])
                lo = p.get('low_alarm')
                hi = p.get('high_alarm')
                if lo is not None or hi is not None:
                    self._ai_thresholds[ch] = (
                        None if lo is None else float(lo),
                        None if hi is None else float(hi),
                    )
                self._ai_scale[ch] = (float(p.get('scale', 1.0) or 1.0),
                                      float(p.get('offset', 0.0) or 0.0))
        except Exception:
            pass

    # ── Public API (thread-safe enqueue) ─────────────────────────
    def write_do(self, channel: int, value: int):
        """Queue a DO bit write request."""
        self._cmd_q.put({'kind': 'do', 'channel': int(channel),
                         'value': 1 if value else 0})

    def write_ao(self, channel: int, raw: Optional[int] = None,
                 percent: Optional[float] = None):
        """Queue an AO register write request (raw 0..65535 or percent)."""
        cmd = {'kind': 'ao', 'channel': int(channel)}
        if raw is not None:
            cmd['raw'] = int(raw) & 0xFFFF
        elif percent is not None:
            cmd['percent'] = float(percent)
        else:
            return
        self._cmd_q.put(cmd)

    # ── Main loop ────────────────────────────────────────────────
    def run(self):
        from datetime import datetime
        self.reload_config()
        if not self._cfg:
            self._emit_conn(False, f"Modül #{self.module_id} bulunamadı")
            return

        ok = self._open_modbus()
        if not ok:
            self._emit_conn(False,
                "Modbus TCP bağlantısı kurulamadı — bekleniyor")
        else:
            self._emit_conn(True,
                f"Bağlı: {self._cfg.get('host')}:{self._cfg.get('port')}")
            coupler = self._read_coupler_id()
            if coupler:
                self._emit_coupler(coupler)

        while not self._stop:
            try:
                # Client yoksa (ilk açılış başarısız oldu ya da hat düştü)
                # her poll döngüsünde reconnect dene.
                if self._client is None:
                    if self._open_modbus():
                        self._emit_conn(True,
                            f"Bağlı: {self._cfg.get('host')}:{self._cfg.get('port')}")
                        coupler = self._read_coupler_id()
                        if coupler:
                            self._emit_coupler(coupler)
                self._handle_commands()
                values = self._poll_once()
                ts = datetime.now().isoformat()
                self.registers_updated.emit(self.module_id, values, ts)
                self._emit_di_edges(values.get('DI', {}), ts)
                self._evaluate_ai_alarms(values.get('AI', {}), ts)
            except Exception as e:
                self._emit_conn(False, f"Hata: {e}")

            # Stop sinyaline duyarlı bekleme. Tick granularity, ya
            # toplam poll süresinin onda biri ya da 50 ms — hangisi
            # küçükse. Bu sayede 1 ms gibi çok küçük poll değerleri
            # gerçek hızda dönerken büyük değerler stop'a 50 ms içinde
            # cevap verir.
            tick = min(0.05, max(0.001, self._poll_sec / 10.0))
            elapsed = 0.0
            while elapsed < self._poll_sec and not self._stop:
                time.sleep(tick)
                elapsed += tick

        self._close_modbus()

    # ── Edge detection ───────────────────────────────────────────
    def _emit_di_edges(self, di_now: Dict[int, int], ts: str):
        """Compare current DI snapshot against previous one and emit a
        di_edge signal for every channel that flipped. First poll is
        treated as the reference (no edges fired).

        Per-channel debounce: an edge is dropped (and prev_di NOT advanced
        for that channel) if it arrives within ``_debounce_sec`` of the
        previously accepted edge for the same channel. This keeps a
        bouncing contact from spamming events; the new stable state will
        be captured on the next poll after the debounce window expires.
        """
        if not di_now:
            return
        cur = {int(ch): 1 if int(b) else 0 for ch, b in di_now.items()}
        if self._prev_di is None:
            self._prev_di = cur
            return
        now = time.monotonic()
        accepted_prev = dict(self._prev_di)
        for ch, val in cur.items():
            prev = accepted_prev.get(ch)
            if prev is None or prev == val:
                continue
            last_t = self._last_edge_t.get(ch, 0.0)
            if self._debounce_sec > 0 and (now - last_t) < self._debounce_sec:
                # Drop this edge; keep prev_di[ch] at its previous accepted
                # value so the next stable reading after the window will
                # be detected as the real transition.
                continue
            self.di_edge.emit(self.module_id, ch, val, ts)
            self._last_edge_t[ch] = now
            accepted_prev[ch] = val
        self._prev_di = accepted_prev

    # ── AI alarm değerlendirmesi (Faz-6g) ────────────────────────
    def _evaluate_ai_alarms(self, ai_now: Dict, ts: str):
        """Her AI kanalı için ölçeklenmiş değeri eşiklerle karşılaştır
        ve durum DEĞİŞTİĞİNDE `ai_alarm` yayınla. Yayınlanan severity:
        'HIGH' (eşik üstüne çıktı), 'LOW' (eşik altına düştü), 'OK'
        (alarm bölgesinden normale döndü). Eşik tanımlı değilse kanal
        atlanır."""
        if not ai_now or not self._ai_thresholds:
            return
        for ch_key, sample in ai_now.items():
            ch = int(ch_key)
            thr = self._ai_thresholds.get(ch)
            if not thr:
                continue
            lo, hi = thr
            try:
                raw = float(sample.get('raw') if isinstance(sample, dict) else sample)
            except (TypeError, ValueError):
                continue
            scale, offset = self._ai_scale.get(ch, (1.0, 0.0))
            eng = scale * raw + offset
            new_state = 'OK'
            crossed = None
            if hi is not None and eng > hi:
                new_state, crossed = 'HIGH', hi
            elif lo is not None and eng < lo:
                new_state, crossed = 'LOW', lo
            prev = self._ai_alarm_state.get(ch, 'OK')
            if new_state == prev:
                continue
            self._ai_alarm_state[ch] = new_state
            # OK'a dönüşte eşik referansı için son ihlali ne ise onu yolla;
            # bilmiyorsak hi veya lo'dan birini geç (informational).
            ref = crossed if crossed is not None else (
                hi if hi is not None else (lo if lo is not None else 0.0)
            )
            self.ai_alarm.emit(self.module_id, ch, new_state,
                               float(eng), float(ref), ts)

    # ── Polling ──────────────────────────────────────────────────
    def _poll_once(self) -> Dict:

        if self._client is None:
            return self._empty_values()

        cfg = self._cfg
        slave = int(cfg.get('unit_id', 255))
        raw_max = int(cfg.get('raw_max', 27648))
        try:
            out_regs = self._read_holding(int(cfg['output_start']),
                                          int(cfg['output_count']), slave)
            in_regs = self._read_holding(int(cfg['input_start']),
                                         int(cfg['input_count']), slave)
        except Exception as e:
            self._emit_conn(False, f"Okuma hatası: {e}")
            return self._empty_values()

        ao_words = int(cfg.get('ao_words', 4))
        do_words = int(cfg.get('do_words', 1))
        ai_words = int(cfg.get('ai_words', 4))
        di_words = int(cfg.get('di_words', 1))

        ao_regs = out_regs[:ao_words]
        do_regs = out_regs[ao_words:ao_words + do_words]
        ai_regs = in_regs[:ai_words]
        di_regs = in_regs[ai_words:ai_words + di_words]

        return {
            'AO': {i: {'raw': r, 'pct': raw_to_percent(r, raw_max)}
                   for i, r in enumerate(ao_regs)},
            'DO': {i: b for i, b in enumerate(_regs_to_bits(do_regs))},
            'AI': {i: {'raw': r, 'pct': raw_to_percent(r, raw_max)}
                   for i, r in enumerate(ai_regs)},
            'DI': {i: b for i, b in enumerate(_regs_to_bits(di_regs))},
        }

    def _empty_values(self) -> Dict:
        cfg = self._cfg or {}
        ao = int(cfg.get('ao_words', 4))
        do = int(cfg.get('do_words', 1)) * 16
        ai = int(cfg.get('ai_words', 4))
        di = int(cfg.get('di_words', 1)) * 16
        return {
            'AO': {i: {'raw': 0, 'pct': 0.0} for i in range(ao)},
            'DO': {i: 0 for i in range(do)},
            'AI': {i: {'raw': 0, 'pct': 0.0} for i in range(ai)},
            'DI': {i: 0 for i in range(di)},
        }

    # ── Command handling (DO/AO writes) ──────────────────────────
    def _handle_commands(self):
        while True:
            try:
                cmd = self._cmd_q.get_nowait()
            except queue.Empty:
                return
            kind = cmd.get('kind')
            try:
                if kind == 'do':
                    self._do_write_do(cmd['channel'], cmd['value'])
                elif kind == 'ao':
                    raw_max = int(self._cfg.get('raw_max', 27648))
                    raw = cmd.get('raw')
                    if raw is None and 'percent' in cmd:
                        raw = percent_to_raw(cmd['percent'], raw_max)
                    self._do_write_ao(cmd['channel'], int(raw) & 0xFFFF)
            except Exception as e:
                ch = cmd.get('channel', -1)
                pt = 'DO' if kind == 'do' else 'AO'
                val = cmd.get('value', cmd.get('raw', cmd.get('percent')))
                self.write_completed.emit(self.module_id, pt, ch, val,
                                          False, str(e))

    def _do_write_do(self, channel: int, value: int):
        cfg = self._cfg
        do_addr = int(cfg['output_start']) + int(cfg.get('ao_words', 4))
        slave = int(cfg.get('unit_id', 255))
        if self._client is None:
            self.write_completed.emit(self.module_id, 'DO', channel, value,
                                      False, 'Modbus bağlı değil')
            return
        rr = self._client.read_holding_registers(address=do_addr, count=1, slave=slave)
        if rr.isError():
            raise RuntimeError(f"DO oku 0x{do_addr:04X}: {rr}")
        cur = rr.registers[0] & 0xFFFF
        mask = 1 << channel
        new = (cur | mask) if value else (cur & ~mask)
        new &= 0xFFFF
        wr = self._client.write_register(address=do_addr, value=new, slave=slave)
        if wr.isError():
            raise RuntimeError(f"DO yaz 0x{do_addr:04X}: {wr}")
        self.write_completed.emit(self.module_id, 'DO', channel, value, True, '')

    def _do_write_ao(self, channel: int, raw: int):
        cfg = self._cfg
        ao_addr = int(cfg['output_start']) + int(channel)
        slave = int(cfg.get('unit_id', 255))
        if self._client is None:
            self.write_completed.emit(self.module_id, 'AO', channel, raw,
                                      False, 'Modbus bağlı değil')
            return
        wr = self._client.write_register(address=ao_addr, value=raw & 0xFFFF,
                                         slave=slave)
        if wr.isError():
            raise RuntimeError(f"AO yaz 0x{ao_addr:04X}: {wr}")
        self.write_completed.emit(self.module_id, 'AO', channel, raw, True, '')

    # ── Modbus TCP helpers ───────────────────────────────────────
    def _open_modbus(self) -> bool:
        try:
            from pymodbus.client import ModbusTcpClient  # type: ignore
        except Exception:
            return False
        cfg = self._cfg
        try:
            self._client = ModbusTcpClient(
                host=cfg.get('host', '127.0.0.1'),
                port=int(cfg.get('port', 502)),
                timeout=float(cfg.get('timeout_sec', 2.0)),
            )
            return bool(self._client.connect())
        except Exception:
            self._client = None
            return False

    def _close_modbus(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _read_holding(self, addr: int, count: int, slave: int):
        rr = self._client.read_holding_registers(address=addr, count=count,
                                                 slave=slave)
        if rr.isError():
            raise RuntimeError(f"adres 0x{addr:04X}: {rr}")
        return list(rr.registers)

    def _read_coupler_id(self) -> str:
        try:
            regs = self._read_holding(0x1000, 8,
                                      int(self._cfg.get('unit_id', 255)))
        except Exception:
            return ''
        swapped = bytearray()
        for r in regs:
            swapped.append(r & 0xFF)
            swapped.append((r >> 8) & 0xFF)
        try:
            return swapped.decode('ascii', errors='replace').strip('\x00 ').strip()
        except Exception:
            return ''
