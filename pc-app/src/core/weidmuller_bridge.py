"""
Weidmüller IO Bridge (Faz-6f) — headless service
================================================

Owns one ``WeidmullerWorker`` per configured (active) Modbus module and
mediates between the workers and the rest of the application:

  * DI edge → barrier event / DOOR audit / PORT motion+occupancy
  * Active batch door_states → DO writes (lock = DO 1, unlock = DO 0)
  * UI panels (IoPanel, OverviewPanel) attach as read-only observers
    via the re-emitted signals (``registers_updated``, ``connection_status``,
    ``coupler_identified``, ``di_edge``, ``write_completed``).

Always-on: instantiated by ``OrapsMainWidget`` regardless of user role,
so an Operator-started batch still drives the physical hardware.

Convention (confirmed 2026-06-19):
  * Door DO = 1  →  electromagnetic lock energised → LOCKED
  * Door DO = 0  →  de-energised                    → OPEN
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSignal

from core.weidmuller_manager import WeidmullerManager
from core.weidmuller_worker import WeidmullerWorker


# DO value semantics (confirmed by user):
DO_LOCKED = 0
DO_OPEN = 1

# Machine-stop DO semantics (saha doğrulaması 2026-08-04):
#   DURDUR → DO=1 (bobin enerjili → NC kontak AÇILIR → devre kesilir → makine durur)
#   ÇALIŞ  → DO=0 (bobin enerjisiz → NC kontak KAPALI → devre tamam → makine çalışır)
MS_DO_STOP = 1
MS_DO_RUN = 0


class WeidmullerBridge(QObject):
    """Headless owner of WeidmullerWorker instances + domain bridges."""

    # Re-emitted from the underlying workers (module_id is always first)
    registers_updated = pyqtSignal(int, dict, str)
    connection_status = pyqtSignal(int, bool, str)
    coupler_identified = pyqtSignal(int, str)
    di_edge = pyqtSignal(int, int, int, str)
    write_completed = pyqtSignal(int, str, int, object, bool, str)
    # Faz-6g: AI alarm eşik aşımı (severity değişimi). UI bunu izleyip
    # banner/popup gösterebilir; audit zaten bridge tarafında yazılır.
    ai_alarm = pyqtSignal(int, int, str, float, float, str)

    # Faz-6d: emitted after a DI edge has been persisted as a
    # light_barrier_events row + ORAPS audit. Args: (barrier_id, state, ts).
    barrier_event_recorded = pyqtSignal(int, int, str)

    # Kapı pozisyon sensörü (DI — link_type='door') değiştiğinde yayın.
    # Args: (door_idx, state). state: 0 = kapalı, 1 = açık.
    door_sensor_changed = pyqtSignal(int, int)

    # Acil stop (DI — link_type='estop') değiştiğinde yayın.
    # Args: (state, ts). state: 1 = basıldı (alarm), 0 = serbest.
    estop_triggered = pyqtSignal(int, str)

    def __init__(self, database, auth_manager, audit_manager,
                 batch_manager, parent=None):
        super().__init__(parent)
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
        self.bm = batch_manager
        self.wm = WeidmullerManager(database, auth_manager, audit_manager)
        self.workers: Dict[int, WeidmullerWorker] = {}
        # door_idx → son bilinen DI sensör durumu (0/1). İlk DI edge
        # gelmeden önce kapı burada yer almaz; UI tarafı yokluk = 0
        # olarak yorumlayabilir.
        self._door_di_state: Dict[int, int] = {}
        # İlk poll'dan sonra kapı DI kanallarını seed etmek için
        # hangi modüllerin seed'lendiğini takip et.
        self._seeded_modules: set = set()
        # Bağlantı durumu: sadece bağlı modüllerden gelen veriyi seed et.
        self._connected_modules: set = set()
        # Acil stop son bilinen durumu: 0 = serbest, 1 = basıldı.
        self._estop_state: int = 0
        # Faz-10: machine_stop DO'larının son yazılan değerleri
        # {(module_id, channel): 0|1} — değişmeyen değer tekrar yazılmaz.
        self._machine_stop_out: Dict[Tuple[int, int], int] = {}
        # Periyodik machine_stop reconcile throttle (monotonic saniye).
        # DB'de rol/link değişikliği, kaçan event veya manuel DO toggle
        # sonrası çıkışlar en geç ~2 sn'de doğru değere çekilir.
        self._ms_last_reconcile: float = 0.0
        # Buzzer DO durumu — iki kaynak OR'lanır: acil stop + alarm banner
        # (Genel Bakış). Değer değişmedikçe yazılmaz.
        self._buzzer_estop = False
        self._buzzer_alarm = False
        self._buzzer_out: Optional[int] = None

    # ── Lifecycle ────────────────────────────────────────────────
    def start_all(self):
        """Spawn one worker per active module. Idempotent."""
        modules = self.wm.list_modules(only_active=True)
        present = set(self.workers.keys())
        for m in modules:
            mid = int(m['id'])
            if mid in present:
                continue
            w = WeidmullerWorker(self.wm, mid)
            self._wire_worker(w)
            self.workers[mid] = w
            w.start()
        # Drop workers whose modules disappeared
        for mid in list(self.workers.keys()):
            if not any(int(m['id']) == mid for m in modules):
                self._stop_worker(mid)

    def stop_all(self):
        for mid in list(self.workers.keys()):
            self._stop_worker(mid)
        # Kapı DI cache'ini temizle — link konfigürasyonu değişmiş olabilir
        # (ör. kullanıcı DI→kapı bağlantısını kaldırdı). Açık görünen
        # kapılara 0 yayınla ki 3D viewer'da bayat turuncu kalmasın.
        # Yeniden başlatınca seed gerçek DI verisiyle tekrar boyar.
        for _didx, _val in list(self._door_di_state.items()):
            if int(_val) == 1:
                try:
                    self.door_sensor_changed.emit(int(_didx), 0)
                except Exception:
                    pass
        self._door_di_state.clear()
        self._seeded_modules.clear()
        self._connected_modules.clear()
        self._machine_stop_out.clear()

    def reload(self):
        """Re-sync to current module list (e.g. after settings change)."""
        self.stop_all()
        self.start_all()

    def _stop_worker(self, module_id: int):
        w = self.workers.pop(module_id, None)
        if not w:
            return
        try:
            w.stop()
            if not w.wait(3000):
                w.terminate()
        except Exception:
            pass

    def _wire_worker(self, w: WeidmullerWorker):
        w.registers_updated.connect(self._on_registers_updated)
        w.registers_updated.connect(self.registers_updated.emit)
        w.connection_status.connect(self._on_connection_status)
        w.connection_status.connect(self.connection_status.emit)
        w.coupler_identified.connect(self.coupler_identified.emit)
        w.write_completed.connect(self.write_completed.emit)
        # Bridge owns the DI edge → audit / barrier routing.
        # We re-emit di_edge AFTER persisting so UI listeners see a
        # consistent ordering (DB row first, then signal).
        w.di_edge.connect(self._on_di_edge)
        w.ai_alarm.connect(self._on_ai_alarm)

    def _on_connection_status(self, module_id: int, connected: bool, msg: str):
        """Modül bağlantı durumu değiştiğinde seed'i sıfırla (yeniden bağlanınca
        güncel DI okunabilsin)."""
        mid = int(module_id)
        if connected:
            self._connected_modules.add(mid)
            # Bağlantı sağlandığında seed'i sıfırla — bir sonraki registers_updated
            # gerçek veriyle gelecek.
            self._seeded_modules.discard(mid)
            # Machine_stop yazım cache'ini bu modül için düşür — coupler
            # resetlenmiş/çıkışları değişmiş olabilir; reconcile yeniden yazsın.
            for key in list(self._machine_stop_out.keys()):
                if key[0] == mid:
                    del self._machine_stop_out[key]
            # Buzzer da yeniden yazılsın (çıkış resetlenmiş olabilir).
            self._buzzer_out = None
        else:
            self._connected_modules.discard(mid)

    def _on_registers_updated(self, module_id: int, values: dict, ts: str):
        """İlk poll verisi geldiğinde kapı DI kanallarının mevcut durumunu
        seed et. Böylece program açıldığında zaten açık olan kapılar hemen
        sarı görünür (edge beklemeden). Ayrıca machine_stop çıkışlarını
        periyodik olarak (>=2 sn arayla) hedef değere çeker — kaçan event,
        sonradan değişen rol/link veya manuel DO müdahalesi kendini toparlar."""
        mid = int(module_id)
        if mid in self._seeded_modules:
            # Seed zaten yapıldı — sadece periyodik reconcile (throttle'lı).
            now = time.monotonic()
            if now - self._ms_last_reconcile >= 2.0:
                self._ms_last_reconcile = now
                self._update_machine_stop_dos()
            return
        # Sadece gerçekten bağlı modüllerden gelen veriyi seed et.
        # Bağlantı yokken _empty_values() döner (tüm DI=0) → yanlış sonuç.
        if mid not in self._connected_modules:
            return
        self._seeded_modules.add(mid)
        di_now = values.get('DI')
        if not di_now:
            return
        try:
            points = self.wm.list_points(module_id=mid, point_type='DI')
        except Exception:
            return
        # group_id → [door_index...] eşlemesi (door_group link'i için).
        group_members: dict = {}
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT group_id, door_index FROM oraps_door_labels '
                'WHERE group_id IS NOT NULL'
            )
            for row in cur.fetchall():
                try:
                    gid = int(row[0]); didx = int(row[1])
                except (TypeError, ValueError):
                    continue
                group_members.setdefault(gid, []).append(didx)
            self.db.close()
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
        for p in points:
            link_type = (p.get('link_type') or '').strip().lower()
            link_id = int(p.get('link_id') or 0)
            if not link_id:
                continue
            if link_type == 'door':
                door_indices = [link_id]
            elif link_type == 'door_group':
                door_indices = group_members.get(link_id, [])
            else:
                continue
            if not door_indices:
                continue
            ch = int(p.get('channel', -1))
            raw_val = di_now.get(ch, di_now.get(str(ch)))
            if raw_val is None:
                continue
            # DI=1 → kapı kapalı, DI=0 → kapı açık (NC sensör konvansiyonu)
            open_flag = 0 if int(raw_val) == 1 else 1
            for door_idx in door_indices:
                if self._door_di_state.get(int(door_idx)) == open_flag:
                    continue  # zaten doğru
                self._door_di_state[int(door_idx)] = open_flag
                self.door_sensor_changed.emit(int(door_idx), open_flag)
        # Faz-10: seed sonrası machine_stop rölelerini gerçek kapı
        # durumlarına göre hizala.
        self._update_machine_stop_dos()

    # ── DI edge routing ──────────────────────────────────────────
    def _on_di_edge(self, module_id: int, channel: int,
                    state: int, ts: str):
        _door_changed = False
        try:
            points = self.wm.list_points(module_id=int(module_id),
                                         point_type='DI')
        except Exception:
            self.di_edge.emit(module_id, channel, state, ts)
            return
        for p in points:
            if int(p.get('channel', -1)) != int(channel):
                continue
            link_type = (p.get('link_type') or '').strip().lower()
            link_id = int(p.get('link_id') or 0)
            if link_type == 'barrier' and link_id:
                self._handle_barrier_edge(link_id, int(module_id),
                                         int(channel), int(state), ts)
            elif link_type == 'door' and link_id:
                # DI on a door = position/end-stop sensor.
                # Faz-9: kablolamaya göre DI=1 → KAPALI, DI=0 → AÇIK.
                # (Röle/NC sensör: kapı kapalıyken kontak temaslı → 1;
                # kapı açılınca temas kesilir → 0.)
                # Faz-13: kapı aktif batch'te KİLİTLİ ise açılma/kapanma
                # FORCED/FORCED_CLOSED olarak loglanır (KP-03/KP-04).
                open_flag = 0 if int(state) == 1 else 1
                _locked = self._door_locked_in_batch(link_id)
                if open_flag:
                    event = 'FORCED' if _locked else 'OPENED'
                else:
                    event = 'FORCED_CLOSED' if _locked else 'CLOSED'
                try:
                    self.bm.log_door_io_event(link_id, event, source='IO')
                except Exception:
                    import traceback; traceback.print_exc()
                # Cache güncelle + 3D viewer için sinyal yay.
                # Cache'de "açık = 1" konvansiyonu — sarı boyama val==1'e
                # bakıyor. Bu yüzden bit'i tersleyerek yayınlıyoruz.
                self._door_di_state[int(link_id)] = open_flag
                self.door_sensor_changed.emit(int(link_id), open_flag)
                _door_changed = True
            elif link_type == 'door_group' and link_id:
                # Grup DI sensörü: gruptaki tüm kapılar için sinyal yay.
                open_flag = 0 if int(state) == 1 else 1
                door_indices = self._get_group_members(link_id)
                for door_idx in door_indices:
                    _locked = self._door_locked_in_batch(door_idx)
                    if open_flag:
                        event = 'FORCED' if _locked else 'OPENED'
                    else:
                        event = 'FORCED_CLOSED' if _locked else 'CLOSED'
                    try:
                        self.bm.log_door_io_event(door_idx, event, source='IO')
                    except Exception:
                        import traceback; traceback.print_exc()
                    self._door_di_state[int(door_idx)] = open_flag
                    self.door_sensor_changed.emit(int(door_idx), open_flag)
                _door_changed = True
            elif link_type == 'port' and link_id:
                try:
                    self.bm.log_port_motion_event(
                        link_id, detected=bool(int(state)), source='IO')
                except Exception:
                    import traceback; traceback.print_exc()
            elif link_type == 'estop':
                # Acil stop: NC kontakt → DI=1 normal, DI=0 basıldı.
                estop_active = 1 if int(state) == 0 else 0
                if estop_active != self._estop_state:
                    self._estop_state = estop_active
                    self.estop_triggered.emit(estop_active, ts)
                    # Audit log
                    if estop_active:
                        self._audit_estop('ESTOP_TRIGGERED',
                                          'Acil stop butonu BASILDI', ts)
                        # Buzzer DO kanalını aç (alarm kaynağıyla OR'lanır)
                        self._buzzer_estop = True
                        self._apply_buzzer()
                        # Aktif batch'i otomatik duraklat
                        self._estop_pause_batch(ts)
                    else:
                        self._audit_estop('ESTOP_RELEASED',
                                          'Acil stop butonu serbest bırakıldı', ts)
                        # Buzzer'ın estop kaynağını kapat
                        self._buzzer_estop = False
                        self._apply_buzzer()
            break
        # Faz-10: kapı durumu değiştiyse machine_stop rölelerini güncelle.
        if _door_changed:
            self._update_machine_stop_dos()
        # Re-emit for UI consumers after persistence.
        self.di_edge.emit(module_id, channel, state, ts)

    # ── Acil stop yardımcı metotları ─────────────────────────────
    def _audit_estop(self, action: str, desc: str, ts: str):
        try:
            if self.audit:
                self.audit.log_action(
                    action_type=action,
                    description=desc,
                    category='ORAPS',
                )
        except Exception:
            pass

    def _set_buzzer_do(self, value: int):
        """Buzzer DO kanallarına value (0/1) yaz — `link_role='buzzer'`
        VEYA `link_type='buzzer'` olan noktalar (ikisi de desteklenir)."""
        try:
            for p in self.wm.list_points(point_type='DO'):
                role = (p.get('link_role') or '').lower().strip()
                lt = (p.get('link_type') or '').lower().strip()
                if role != 'buzzer' and lt != 'buzzer':
                    continue
                w = self.workers.get(int(p['module_id']))
                if w:
                    w.write_do(int(p['channel']), int(value))
        except Exception:
            pass

    def _apply_buzzer(self):
        """Buzzer hedef değerini (estop OR alarm) hesapla; değiştiyse yaz."""
        want = 1 if (self._buzzer_estop or self._buzzer_alarm) else 0
        if self._buzzer_out == want:
            return
        self._buzzer_out = want
        self._set_buzzer_do(want)

    def set_alarm_buzzer(self, active: bool):
        """Genel Bakış alarm şeridi kaynaklı buzzer isteği.

        Banner yanıyor (bariyer, makine durdurma, zorla kapı açma, LAF,
        acil stop …) → rol='buzzer' DO'lar 1; banner söndü/onaylandı → 0.
        Acil stop kaynaklı buzzer ile OR'lanır."""
        self._buzzer_alarm = bool(active)
        self._apply_buzzer()

    def _estop_pause_batch(self, ts: str):
        """Acil stop basıldığında aktif batch'i otomatik duraklat."""
        try:
            ab = self.bm.get_active_batch()
            if ab and ab.get('status') == 'running':
                self.bm.pause_batch_interlock(reason='Acil stop butonu basıldı')
        except Exception:
            pass

    def get_estop_state(self) -> int:
        """Acil stop son bilinen durumu. 0 = serbest, 1 = basıldı."""
        return self._estop_state

    def _door_locked_in_batch(self, door_idx: int) -> bool:
        """Faz-13: kapı şu an aktif batch'in ORABS aşamasında 'locked' mı?
        FORCED (kilitli kapı açıldı) tespiti için kullanılır. GLT aşamasında
        tüm kapılar serbest olduğu için False döner."""
        try:
            ab = self.bm.get_active_batch()
        except Exception:
            return False
        if not ab or (ab.get('status') or '') not in ('running', 'paused'):
            return False
        if (ab.get('phase') or 'orabs') == 'glt':
            return False
        states = ab.get('door_states') or {}
        return str(states.get(str(int(door_idx)), '')).lower() == 'locked'

    def _get_group_members(self, group_id: int) -> list:
        """group_id → [door_index, ...] listesi döndürür (kilit grubu)."""
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT door_index FROM oraps_door_labels WHERE group_id=?',
                (int(group_id),)
            )
            result = [int(r[0]) for r in cur.fetchall()]
            self.db.close()
            return result
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return []

    def _get_stop_group_members(self, group_id: int) -> list:
        """group_id → [door_index, ...] — makine durdurma grubu üyeliği.

        Önce Faz-10b `stop_group_id` üyeliğine bakılır; O BOŞSA kilit
        grubu (`group_id`) üyeliğine düşülür (2026-08-04). Böylece
        kullanıcı kapıları yalnız 'Grup' (kilit) satırından atadıysa da
        machine_stop DO'su tetiklenebilir; ayrı durdurma üyeliği
        tanımlanmışsa o öncelikli kalır."""
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT door_index FROM oraps_door_labels '
                'WHERE stop_group_id=?',
                (int(group_id),)
            )
            result = [int(r[0]) for r in cur.fetchall()]
            if not result:
                cur.execute(
                    'SELECT door_index FROM oraps_door_labels '
                    'WHERE group_id=?',
                    (int(group_id),)
                )
                result = [int(r[0]) for r in cur.fetchall()]
            self.db.close()
            return result
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return []

    def _handle_barrier_edge(self, barrier_id: int, module_id: int,
                             channel: int, state: int, ts: str):
        try:
            event_id = self.bm.record_barrier_event(
                barrier_id=barrier_id, module_id=module_id,
                channel=channel, state=state, ts=ts,
            )
        except Exception:
            import traceback; traceback.print_exc()
            return
        if event_id is not None:
            self.barrier_event_recorded.emit(barrier_id, state, ts)
            # Faz-6e: bariyer KESİLDİĞİNDE (state=1) ve aktif batch
            # 'running' iken interlock ihlali. auto_pause=1 ise batch'i
            # otomatik duraklat.
            if int(state) == 1:
                self._trigger_interlock(barrier_id, ts)

    # ── Faz-6e batch interlock ───────────────────────────────────
    def _trigger_interlock(self, barrier_id: int, ts: str):
        """Aktif batch 'running' iken bariyer kesildi → audit + opsiyonel
        auto-pause. setting 'oraps_barrier_auto_pause'='1' ise batch
        system_interlock_pause ile durdurulur."""
        try:
            ab = self.bm.get_active_batch()
            if not ab or ab.get('status') != 'running':
                return
            try:
                auto = int(self.db.get_setting('oraps_barrier_auto_pause', '0'))
            except (TypeError, ValueError):
                auto = 0
            reason = f"Bariyer #{barrier_id} tetiklendi ({ts})"
            if auto:
                self.bm.system_interlock_pause(reason)
            else:
                # Audit-only: bilgilendirme amaçlı
                try:
                    self.audit.log_action(
                        action_type='BATCH_INTERLOCK_TRIPPED',
                        description=(
                            f"Bariyer interlock (auto_pause kapalı): "
                            f"batch '{ab.get('batch_name')}' devam ediyor — {reason}"
                        ),
                        table_name='active_batch',
                        category='ORAPS',
                    )
                except Exception:
                    pass
        except Exception:
            import traceback; traceback.print_exc()

    # ── AI alarm routing (Faz-6g) ────────────────────────────────
    def _on_ai_alarm(self, module_id: int, channel: int, severity: str,
                     value: float, threshold: float, ts: str):
        """Worker'dan gelen AI alarm severity değişikliklerini ORAPS audit
        kategorisine yazar ve UI dinleyicilerine yeniden yayınlar.
        Action type'lar: AI_ALARM_HIGH, AI_ALARM_LOW, AI_ALARM_OK."""
        try:
            label = f"AI{int(channel)}"
            unit = ''
            for p in self.wm.list_points(module_id=int(module_id),
                                          point_type='AI'):
                if int(p.get('channel', -1)) == int(channel):
                    label = f"AI{channel} '{p.get('name', '')}'"
                    unit = p.get('unit', '') or ''
                    break
            action = f"AI_ALARM_{severity}"
            if severity == 'OK':
                desc = (f"AI alarm normale döndü: modül {module_id} {label} "
                        f"= {value:.3f}{unit}")
            else:
                cmp_op = '>' if severity == 'HIGH' else '<'
                desc = (f"AI alarm {severity}: modül {module_id} {label} "
                        f"= {value:.3f}{unit} {cmp_op} {threshold:.3f}{unit}")
            try:
                self.audit.log_action(
                    action_type=action,
                    table_name='weidmuller_io_points',
                    record_id=None,
                    description=desc,
                    new_value=f"{value:.3f}",
                    old_value=f"thr={threshold:.3f}",
                    category='ORAPS',
                )
            except Exception:
                pass
        except Exception:
            import traceback; traceback.print_exc()
        finally:
            self.ai_alarm.emit(module_id, channel, severity,
                               float(value), float(threshold), ts)

    # ── Door locks: batch_changed → DO writes ────────────────────
    def get_door_sensor_states(self) -> Dict[int, int]:
        """door_idx → 0/1 son bilinen DI sensör değerlerinin kopyası.
        UI tarafı bu cache'i okuyup sensor=1 olan kapıları 'sensor_open'
        (sarı) olarak gösterir. İlk DI edge gelmeden önce kapı burada
        yoktur."""
        return dict(self._door_di_state)

    def get_lock_output_targets(self) -> Tuple[set, set]:
        """DO (kilit) çıkışına bağlı kapı ve kapı gruplarını döndür.

        Batch config dialog'unda yalnızca gerçekten kilit DO'suna bağlı
        olan gruplar/kapılar gösterilsin diye kullanılır.

        Return:
            (doors_with_do, groups_with_do) — sırasıyla `link_type='door'` ve
            `link_type='door_group'` DO noktalarından toplanan
            {door_index} ve {group_id} setleri.  `link_role` boş ya da
            'kilit' olan noktalar dahil edilir (diğer role'ler filtrelenir).
        """
        doors_with_do: set = set()
        groups_with_do: set = set()
        try:
            points = self.wm.list_points(point_type='DO')
        except Exception:
            return doors_with_do, groups_with_do
        for p in points:
            lt = (p.get('link_type') or '').lower().strip()
            role = (p.get('link_role') or '').lower().strip()
            if role and role != 'kilit':
                continue
            try:
                link_id = int(p.get('link_id') or 0)
            except (TypeError, ValueError):
                continue
            if link_id <= 0:
                continue
            if lt == 'door':
                doors_with_do.add(link_id)
            elif lt == 'door_group':
                groups_with_do.add(link_id)
        return doors_with_do, groups_with_do

    def get_machine_stop_targets(self) -> Tuple[set, set]:
        """`link_role='machine_stop'` DO'larına bağlı kapı ve grup setleri.

        Batch config dialogunda "Makine Durdurma Grupları" bölümünü
        doldurmak için kullanılır.
        Return: (doors_with_stop_do, groups_with_stop_do)"""
        doors: set = set()
        groups: set = set()
        try:
            points = self.wm.list_points(point_type='DO')
        except Exception:
            return doors, groups
        for p in points:
            if (p.get('link_role') or '').lower().strip() != 'machine_stop':
                continue
            lt = (p.get('link_type') or '').lower().strip()
            try:
                link_id = int(p.get('link_id') or 0)
            except (TypeError, ValueError):
                continue
            if link_id <= 0:
                continue
            if lt == 'door':
                doors.add(link_id)
            elif lt == 'door_group':
                groups.add(link_id)
        return doors, groups

    def compute_door_lock_writes(
            self, door_states: Dict
    ) -> List[Tuple[int, int, int]]:
        """For the given door_states dict ({door_idx_str: 'open'|'locked'}),
        return a list of (module_id, do_channel, value) tuples covering
        every IO point linked as (link_type='door', point_type='DO',
        link_role='kilit'). Doors without a state entry are left alone.

        DO=0 → KİLİTLİ, DO=1 → AÇIK (Faz-9, kullanıcı 2026-07-07 sunum
        donanım kablolamasına göre ters çevrildi; röle NC → DO=1'de
        enerji verildiğinde kilit açılır).

        Faz-9 link tipleri:
          • `link_type='door'`, `link_id=door_index` → tekil kapı bağlantısı.
          • `link_type='door_group'`, `link_id=group_id` → grup bağlantısı;
            grubun içindeki kapılardan ilkinin state'i DO'ya yazılır (config
            grup bazlı hazırlandığı için grup üyelerinin state'i eşittir).
        """
        if not door_states:
            return []
        # Normalize state keys to int
        norm: Dict[int, str] = {}
        for k, v in door_states.items():
            try:
                norm[int(k)] = str(v)
            except (TypeError, ValueError):
                continue

        # group_id → [door_index...] eşlemesi (door_group link'i için gerekli).
        # oraps_door_labels üzerinden tek sorgu.
        group_members: Dict[int, List[int]] = {}
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                'SELECT group_id, door_index FROM oraps_door_labels '
                'WHERE group_id IS NOT NULL'
            )
            for row in cur.fetchall():
                try:
                    gid = int(row[0]); didx = int(row[1])
                except (TypeError, ValueError):
                    continue
                group_members.setdefault(gid, []).append(didx)
            self.db.close()
        except Exception:
            try: self.db.close()
            except Exception: pass

        writes: List[Tuple[int, int, int]] = []
        for p in self.wm.list_points(point_type='DO'):
            lt = (p.get('link_type') or '').lower().strip()
            role = (p.get('link_role') or '').lower().strip()
            if role and role != 'kilit':
                continue   # only act on lock-channel DOs
            state = None
            if lt == 'door':
                door_idx = int(p.get('link_id') or 0)
                if door_idx <= 0:
                    continue
                state = norm.get(door_idx)
            elif lt == 'door_group':
                gid = int(p.get('link_id') or 0)
                members = group_members.get(gid) or []
                # Grup içindeki state'lerin ilkini al (aynı olmalı).
                for didx in members:
                    if didx in norm:
                        state = norm[didx]
                        break
            else:
                continue
            if state is None:
                continue
            value = DO_OPEN if state.lower() == 'open' else DO_LOCKED
            writes.append((int(p['module_id']), int(p['channel']), value))
        return writes

    def apply_door_locks(self, door_states: Dict) -> int:
        """Push the door_states dict to the matching DO worker queues.
        Returns number of write commands enqueued. Missing/inactive workers
        are silently skipped (the operator will see the gap when the
        worker reconnects)."""
        writes = self.compute_door_lock_writes(door_states or {})
        n = 0
        for mid, ch, val in writes:
            w = self.workers.get(int(mid))
            if not w:
                continue
            try:
                w.write_do(int(ch), int(val))
                n += 1
            except Exception:
                import traceback; traceback.print_exc()
        return n

    def _release_all_door_locks(self) -> int:
        """Tüm bağlı DO kilitlerini AÇIK duruma (DO_OPEN=1) getir.
        Batch bittiğinde/idle olduğunda çağrılır — kilitler enerjilendirilir
        ve kapılar açık kalır. `link_type` in ('door','door_group')
        + `link_role='kilit'` (veya boş) filtreleri kullanılır.
        Return: gönderilen komut sayısı.
        """
        writes: List[Tuple[int, int, int]] = []
        for p in self.wm.list_points(point_type='DO'):
            lt = (p.get('link_type') or '').lower().strip()
            if lt not in ('door', 'door_group'):
                continue
            role = (p.get('link_role') or '').lower().strip()
            if role and role != 'kilit':
                continue
            writes.append((int(p['module_id']), int(p['channel']), DO_OPEN))
        n = 0
        for mid, ch, val in writes:
            w = self.workers.get(int(mid))
            if not w:
                continue
            try:
                w.write_do(int(ch), int(val))
                n += 1
            except Exception:
                import traceback; traceback.print_exc()
        return n

    def on_batch_changed(self):
        """Slot for batch_panel.batch_changed. Drives DO outputs from the
        currently active batch.

        Faz-9: Batch bittiğinde (`status='finished'` veya `active_batch` yok)
        tüm bağlı kilit DO'ları AÇIK (DO_OPEN) yapılır — kapılar bir
        sonraki batch başlayana kadar serbest kalır.
        """
        ab = self.bm.get_active_batch()
        status = (ab.get('status') if ab else '') or ''
        _phase = (ab.get('phase') or 'orabs') if ab else 'orabs'
        if status in ('running', 'paused'):
            if _phase == 'glt':
                # Faz-12: GLT aşamasında TÜM kapılar açık tutulur — kilit
                # yazılmaz. Kilitler ORABS aşamasına geçişte uygulanır.
                self._release_all_door_locks()
            else:
                states = (ab.get('door_states') if ab else {}) or {}
                self.apply_door_locks(states)
        else:
            # Batch bitti/idle → tüm kilitleri aç.
            self._release_all_door_locks()
        # Batch_complete DO sinyali: tüm seçili portlar tamamlandıysa
        # link_role='batch_complete' olan DO'yu 1 yap; aksi halde 0.
        self._update_batch_complete_signal(ab)
        # Faz-10: batch durumu machine_stop kapılamasını etkiler
        # (yalnız running/paused iken tetiklenir) → yeniden hesapla.
        self._update_machine_stop_dos()

    # ── Faz-10: kapı açılınca makine durdurma rölesi ─────────────
    def _update_machine_stop_dos(self):
        """`link_role='machine_stop'` DO'larını sür — 3 katman (Faz-12):

          1. Bağlı kapılardan biri AÇIKSA → DURDUR, hepsi kapalıysa ÇALIŞ.
             Batch şartı YOK (2026-08-04): kapak açık = makine durur, her
             zaman. Yalnız ORABS batch'i çalışırken config'teki
             stop_group_ids seçimi uygulanır (seçilmemiş grup tetiklemez).
          2. GLT aşaması (phase='glt'): TÜM machine_stop röleleri DURDUR —
             ORABS aşamasına geçilene kadar makine başlayamaz.
          3. Batch yok/bitti: `oraps_machine_stop_idle`='1' ise TÜMÜ DURDUR
             (ORABS dışı her zaman durdur); değilse katman 1 geçerli.

        Fiziksel yazım: DURDUR → DO=MS_DO_STOP(1) (bobin enerjili → NC
        açılır → devre kesilir), ÇALIŞ → DO=MS_DO_RUN(0) (bobin enerjisiz
        → NC kapalı → devre tamam). `_machine_stop_out` cache'i ve audit
        MANTIKSAL değeri tutar (1=durdur, 0=çalış).

        Değer değişmedikçe yazma/audit yapılmaz. Kilit mantığına karışmaz."""
        try:
            points = [
                p for p in self.wm.list_points(point_type='DO')
                if (p.get('link_role') or '').lower().strip() == 'machine_stop'
                and (p.get('link_type') or '').lower().strip() in
                    ('door', 'door_group')
            ]
        except Exception:
            return
        if not points:
            return
        try:
            ab = self.bm.get_active_batch()
        except Exception:
            ab = None
        status = (ab.get('status') if ab else '') or ''
        _phase = (ab.get('phase') or 'orabs') if ab else 'orabs'
        batch_active = status in ('running', 'paused')
        orabs_running = batch_active and _phase != 'glt'
        glt_running = batch_active and _phase == 'glt'
        # Katman 3 ayarı: ORABS dışı her zaman durdur.
        try:
            idle_stop = str(self.db.get_setting(
                'oraps_machine_stop_idle', '0')).strip() == '1'
        except Exception:
            idle_stop = False
        force_all_stop = glt_running or (not batch_active and idle_stop)
        # Faz-10: config'te seçim yapıldıysa yalnız seçili gruplar tetikler.
        stop_sel = ab.get('stop_group_ids') if ab else None
        if stop_sel is not None:
            try:
                stop_sel = {int(g) for g in stop_sel}
            except (TypeError, ValueError):
                stop_sel = None
        # Kapak adları (audit metni için): kullanıcı etiketi → yoksa 'Kapı N'.
        try:
            _door_names = {
                int(d['door_index']): (d.get('label') or '').strip()
                for d in (self.bm.get_door_labels() or [])
            }
        except Exception:
            _door_names = {}
        # Aynı döngüde birden fazla DO aynı gruba bağlıysa (örn. DO6+DO7)
        # tek audit kaydı yeter — (action, desc) bazında dedupe.
        _audited: set = set()

        for p in points:
            lt = (p.get('link_type') or '').lower().strip()
            try:
                link_id = int(p.get('link_id') or 0)
            except (TypeError, ValueError):
                continue
            if link_id <= 0:
                continue
            # Faz-10b: durdurma grubu üyeliği stop_group_id kolonundan gelir
            # (kilit grubu group_id'den BAĞIMSIZ).
            doors = [link_id] if lt == 'door' \
                else self._get_stop_group_members(link_id)
            open_doors = sorted(
                int(d) for d in doors
                if int(self._door_di_state.get(int(d), 0)) == 1
            )
            if force_all_stop:
                value = 1
            else:
                # 2026-08-04: durdurma grubuna bağlı kapaklar HER ZAMAN
                # tetikler — batch şartı yok. Yalnız ORABS batch'inde
                # config'te seçim yapılmışsa seçilmemiş gruplar devre dışı.
                armed = True
                if orabs_running and lt == 'door_group' \
                        and stop_sel is not None and link_id not in stop_sel:
                    armed = False   # bu batch'te seçilmemiş grup
                value = 1 if (armed and open_doors) else 0
            key = (int(p['module_id']), int(p['channel']))
            if self._machine_stop_out.get(key) == value:
                continue   # değişiklik yok → yazma/audit yok
            w = self.workers.get(key[0])
            if not w:
                # Worker yok → cache'i GÜNCELLEME; sonraki reconcile'da
                # tekrar denenir (cache zehirlenmesi önlenir).
                continue
            try:
                # DURDUR=1 (NC açılır, devre kesilir), ÇALIŞ=0.
                w.write_do(key[1], MS_DO_STOP if value else MS_DO_RUN)
            except Exception:
                import traceback; traceback.print_exc()
                continue   # yazılamadı → cache güncellenmesin, retry olsun
            self._machine_stop_out[key] = value
            try:
                if value:
                    action = 'MACHINE_STOP_TRIGGERED'
                    # Faz-13: varyant kodları emisyon noktasında yazılır;
                    # audit hook '[' görünce tekrar kod eklemez.
                    if force_all_stop and glt_running:
                        desc = "[MS-03] Makine durdurma aktif (GLT aşaması)"
                    elif force_all_stop:
                        desc = ("[MS-04] Makine durdurma aktif "
                                "(batch dışı kilit)")
                    else:
                        _names = ', '.join(
                            _door_names.get(d) or f'Kapı {d}'
                            for d in open_doors)
                        desc = f"Makine durdurma tetiklendi — açık: {_names}"
                else:
                    action = 'MACHINE_STOP_CLEARED'
                    desc = "Makine durdurma temizlendi — kapaklar kapalı"
                if (action, desc) in _audited:
                    continue   # aynı mesaj bu döngüde zaten yazıldı
                _audited.add((action, desc))
                if self.audit:
                    self.audit.log_action(
                        action_type=action,
                        table_name='weidmuller_io_points',
                        record_id=int(p.get('id') or 0) or None,
                        description=desc,
                        category='ORAPS',
                    )
            except Exception:
                pass

    def _update_batch_complete_signal(self, ab=None):
        """Batch'teki tüm seçili portların testi tamamlandı mı kontrol et.
        Tamamlandıysa link_role='batch_complete' DO kanalına 1 yaz (makine
        çalışabilir). Aksi halde 0 (makine bloklu).

        Kullanıcı IO ayarlarından herhangi bir DO noktasını
        link_role='batch_complete' olarak ayarlar — burada otomatik bulunur.
        """
        # batch_complete rolüne sahip DO noktalarını bul
        try:
            bc_points = [
                p for p in self.wm.list_points(point_type='DO')
                if (p.get('link_role') or '').lower().strip() == 'batch_complete'
            ]
        except Exception:
            return
        if not bc_points:
            return  # Kullanıcı henüz bir DO kanalını batch_complete'e bağlamamış

        # Aktif batch var mı ve portlar tanımlı mı?
        if ab is None:
            ab = self.bm.get_active_batch()
        status = (ab.get('status') if ab else '') or ''
        port_indices = (ab.get('port_indices') if ab else []) or []

        all_done = False
        if status in ('running', 'paused') and port_indices:
            # Her seçili port'un test durumunu kontrol et.
            # batch_ports veya test_records üzerinden PASS/FAIL var mı bak.
            try:
                all_done = self._check_ports_completed(port_indices)
            except Exception:
                all_done = False
        elif status in ('finished', 'idle', ''):
            # Batch yok veya bitti → sinyal 0 (varsayılan güvenli durum)
            all_done = False

        value = 1 if all_done else 0
        for p in bc_points:
            w = self.workers.get(int(p['module_id']))
            if w:
                try:
                    w.write_do(int(p['channel']), value)
                except Exception:
                    pass

    def _check_ports_completed(self, port_indices: list) -> bool:
        """Batch'teki tüm seçili portların test tamamlanmış olup olmadığını
        kontrol et. ORAPS port_labels'taki rfid_tag üzerinden test_records'ta
        COMPLETED/FAILED kaydı aranır."""
        if not port_indices:
            return False
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            # Aktif batch başlangıç zamanı
            cur.execute("SELECT started_at FROM active_batch WHERE id=1")
            row = cur.fetchone()
            if not row or not row[0]:
                self.db.close()
                return False
            batch_start = row[0]
            # Her port'un rfid_tag'ini al
            placeholders = ','.join('?' * len(port_indices))
            cur.execute(
                f'SELECT port_index, rfid_tag FROM oraps_port_labels '
                f'WHERE port_index IN ({placeholders})',
                port_indices,
            )
            port_rfids = {int(r['port_index']): r['rfid_tag'] for r in cur.fetchall()}
            self.db.close()
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return False

        # Batch başlangıcından beri tamamlanan testlerin NORMALİZE RFID seti.
        # Cihaz 'DA0DAE' ↔ PC '0x00DA0DAE' format farkı birebir eşleşmeyi
        # boşa düşürüyordu (bug 2026-08-03) → normalize karşılaştır.
        from core.database import normalize_rfid
        try:
            conn = self.db.connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT glove_batch_number FROM test_records "
                "WHERE test_start_time>=? "
                "AND test_status IN ('COMPLETED','FAILED')",
                (batch_start,),
            )
            done_tags = {normalize_rfid(r[0]) for r in cur.fetchall() if r[0]}
            self.db.close()
        except Exception:
            try:
                self.db.close()
            except Exception:
                pass
            return False

        for pidx in port_indices:
            rfid = (port_rfids.get(int(pidx)) or '').strip()
            if not rfid:
                return False  # RFID atanmamış port → tamamlanmamış sayılır
            if normalize_rfid(rfid) not in done_tags:
                return False  # Bu port henüz test edilmemiş
        return True

    def check_batch_complete(self):
        """Dışarıdan (test kaydedildiğinde) çağrılır — batch_complete
        DO sinyalini günceller."""
        self._update_batch_complete_signal()
