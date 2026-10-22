"""
PDF Report Generator
Creates 21 CFR Part 11 compliant PDF reports
"""

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4 as _A4_SIZE
from datetime import datetime
from utils.date_format import format_datetime_tr, now_tr
from typing import Dict, Any, List, Optional
import os
import json
import re
import base64
from utils.app_logger import get_logger

_logger = get_logger("pdf_generator")


def _decode_port_display(port_val) -> str:
    """Port numarasını gösterim formatına çevir: encoded int -> 'sol/sag' veya tek sayı"""
    if port_val is None or port_val == 'N/A':
        return 'N/A'
    try:
        p = int(port_val)
    except (ValueError, TypeError):
        return str(port_val)
    if p == 0:
        return '0'
    if p < 256:
        return str(p)
    left = p >> 8
    right = p & 0xFF
    return f"{left}/{right}"


# Register Arial fonts for Turkish character support (ş, ğ, ı, ü, ö, ç, İ, Ş, Ğ)
def _resolve_font_path(filename):
    """Resolve font path: project assets -> Windows system -> None"""
    # 1. Project-local assets/fonts/
    local = os.path.join(os.path.dirname(__file__), '..', 'assets', 'fonts', filename)
    if os.path.exists(local):
        return os.path.normpath(local)
    # 2. Windows system fonts
    win = os.path.join('C:/Windows/Fonts', filename)
    if os.path.exists(win):
        return win
    return None

try:
    _arial_path   = _resolve_font_path('arial.ttf')
    _arialb_path  = _resolve_font_path('arialbd.ttf')
    if _arial_path and _arialb_path:
        pdfmetrics.registerFont(TTFont('Arial',  _arial_path))
        pdfmetrics.registerFont(TTFont('ArialB', _arialb_path))
        _FONT = 'Arial'
        _FONT_BOLD = 'ArialB'
    else:
        raise FileNotFoundError('Arial fonts not found')
except Exception:
    _FONT = 'Helvetica'
    _FONT_BOLD = 'Helvetica-Bold'

import matplotlib
matplotlib.use('Agg')  # Use non-GUI backend
import matplotlib.pyplot as plt
import numpy as np
import tempfile
from reportlab.pdfgen.canvas import Canvas
from utils.translations import Translations


class NumberedCanvas(Canvas):
    """Canvas that adds page numbering to every page."""
    _lang = 'tr'  # overridden via _make_numbered_canvas()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        """Save current page state WITHOUT flushing to PDF yet."""
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()  # Reset for next page without writing

    def save(self):
        """Write all pages with correct page numbering."""
        total = len(self._saved_page_states)
        page_word = Translations.t('pdf_page', self._lang)
        for idx, state in enumerate(self._saved_page_states, 1):
            self.__dict__.update(state)
            self.setFont(_FONT, 8)
            w, _h = _A4_SIZE
            self.drawCentredString(w / 2, 25, f"{page_word} {idx}/{total}")
            Canvas.showPage(self)
        Canvas.save(self)


def _make_numbered_canvas(lang='tr'):
    """Create a NumberedCanvas subclass with the given language."""
    class _NC(NumberedCanvas):
        _lang = lang
    return _NC


class PDFReportGenerator:
    """Generate PDF reports for test results and audit trails"""
    
    def __init__(self, database, output_dir: str = "reports", batch_output_dir: str = "batches"):
        self.db = database
        self.output_dir = output_dir
        self.batch_output_dir = batch_output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(batch_output_dir, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _resolve_logo_path(self) -> str:
        """Resolve company logo path from DB, falling back to src/assets/logo.png"""
        # Önce rapor ayarlarından özel logo kontrol et
        try:
            report_logo = self.db.get_setting('report_logo_path', '')
            if report_logo and os.path.exists(report_logo):
                return report_logo
        except Exception:
            pass
        logo_path = self.db.get_setting('company_logo_path', 'assets/logo.png')
        if os.path.isabs(logo_path) and os.path.exists(logo_path):
            return logo_path
        if os.path.exists(logo_path):
            return os.path.abspath(logo_path)
        # Try relative to src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_path = os.path.join(src_dir, logo_path)
        if os.path.exists(abs_path):
            return abs_path
        return logo_path

    def _get_report_setting(self, key: str, default: str) -> str:
        """DB'den rapor ayarı oku; yoksa default döner."""
        try:
            val = self.db.get_setting(key, default)
            return val.strip() if val else default
        except Exception:
            return default

    def _company_name(self) -> str:
        return self._get_report_setting(
            'report_company_name', 'Bilim İlaç Sanayi ve Ticaret A.Ş.'
        )

    def _glt_report_title(self) -> str:
        return self._get_report_setting(
            'report_glt_title', 'Eldiven Sızdırmazlık Test Sonuç Raporu'
        )

    def _batch_report_title(self) -> str:
        return self._get_report_setting(
            'report_batch_title', 'Batch Özet Raporu'
        )

    def _audit_report_title(self) -> str:
        return self._get_report_setting(
            'report_audit_title', 'Audit Trail Raporu'
        )
    
    @staticmethod
    def _decode_device_id_to_mac(device_id: str) -> str:
        """LCC_XXXXXXXX formatındaki device_id'den MAC adresini çöz.
        ESP32 tarafı 6-byte MAC'i Base64url (RFC4648 §5) ile 8 karaktere kodluyor.
        Geri çevirip AA:BB:CC:DD:EE:FF formatında döndürür."""
        prefix = 'LCC_'
        if device_id.startswith(prefix):
            encoded = device_id[len(prefix):]
        else:
            encoded = device_id
        if len(encoded) != 8:
            return device_id  # Çözümlenemezse olduğu gibi döndür
        try:
            # Base64url → standart base64 dönüşümü
            b64std = encoded.replace('-', '+').replace('_', '/')
            mac_bytes = base64.b64decode(b64std)
            if len(mac_bytes) != 6:
                return device_id
            # 6 byte MAC → 15 haneli decimal seri numarası (123-1629-8220-6464 formatı)
            mac_int = int.from_bytes(mac_bytes, byteorder='big')
            s = f'{mac_int:015d}'
            return f'{s[:3]}-{s[3:7]}-{s[7:11]}-{s[11:15]}'
        except Exception:
            _logger.debug("Device ID decode failed for: %s", device_id)
            return device_id

    def _setup_custom_styles(self):
        """Setup custom paragraph styles with Turkish character support"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontName=_FONT_BOLD,
            fontSize=16,
            textColor=colors.HexColor('#003366'),
            spaceAfter=6,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontName=_FONT_BOLD,
            fontSize=12,
            textColor=colors.HexColor('#003366'),
            spaceAfter=4,
            spaceBefore=8
        ))
        
        # Override default Normal style to use Arial
        self.styles['Normal'].fontName = _FONT
        self.styles['Normal'].fontSize = 10
    
    
    def _generate_test_graph(self, test_data: Dict[str, Any], lang: str = 'tr') -> str:
        """
        Generate dual-panel test visualization:
          Top:    Real measured pressure data — line color changes per phase (t1/t2/t3)
          Bottom: Theoretical recipe curve with dynamic recipe parameter values
        Both panels on the same figure, stacked vertically.
        Returns: Path to generated graph image
        """
        try:
            _t = lambda k: Translations.t(k, lang)
            data_json = test_data.get('data_json', '{}')
            if isinstance(data_json, str):
                test_measurements = json.loads(data_json)
            else:
                test_measurements = data_json
            
            pressure_data = test_measurements.get('pressure_readings', [])
            time_data = test_measurements.get('time_points', [])
            t1_index = test_measurements.get('t1_index')  # PRE_INFLATION end
            t2_index = test_measurements.get('t2_index')  # CONDITIONING end
            
            # ── Recipe parameters ────────────────────────────────────
            recipe_id = test_measurements.get('recipe_id')
            p1_target, p2_hyst, p3_limit, p8_drop = 500, 50, 100, 150
            t1_sec, t2_sec, t3_sec = 10, 10, 60

            if recipe_id:
                try:
                    conn = self.db.connect()
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM recipes WHERE id = ?', (recipe_id,))
                    recipe = cursor.fetchone()
                    if recipe:
                        rd = dict(recipe)
                        p1_target = rd.get('p1_pressure', 500)
                        p2_hyst = rd.get('p2_hysteresis', 50)
                        p3_limit = rd.get('p3_limit', 100)
                        p8_drop = rd.get('p8_success_drop', rd.get('success_drop', 150))
                        t1_sec = rd.get('t1_inflation', 10)
                        t2_sec = rd.get('t2_stabilization', 10)
                        t3_sec = rd.get('t3_measurement', 60)
                    self.db.close()
                except Exception as e:
                    _logger.warning("Recipe params lookup error: %s", e)
            
            if not recipe_id:
                rp = test_measurements.get('recipe_params', {})
                if rp:
                    p1_target = rp.get('p2', p1_target)
                    p3_limit = rp.get('p6', p3_limit)
                    p8_drop = rp.get('p8', p8_drop)
                    t1_sec = rp.get('p1', t1_sec)
                    t2_sec = rp.get('p3', t2_sec)
                    t3_sec = rp.get('p7', t3_sec)
            
            if 'success_drop' in test_measurements:
                p8_drop = test_measurements['success_drop']
            elif 'window_drop_limit' in test_measurements:
                p8_drop = test_measurements['window_drop_limit']
            
            esp_start_pressure = test_measurements.get('start_pressure')
            esp_pass_limit     = test_measurements.get('pass_limit')
            
            actual_p1 = p1_target
            if esp_start_pressure is not None:
                try:
                    actual_p1 = float(esp_start_pressure)
                except (TypeError, ValueError):
                    pass
            
            has_real_data = pressure_data and time_data and len(pressure_data) > 0
            
            # Measured phase durations (will be set from real data, used in bottom graph too)
            measured_t1 = None  # Actual inflation duration
            measured_t2 = None  # Actual stabilization duration
            measured_t3 = None  # Actual test duration
            
            # ── Create dual-panel figure ─────────────────────────────
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 10), dpi=100,
                                           gridspec_kw={'height_ratios': [3, 2], 'hspace': 0.35})
            fig.patch.set_facecolor('white')
            
            # ════════════════════════════════════════════════════════
            # ██  TOP PANEL (ax1) — Measured data, colored line      ██
            # ════════════════════════════════════════════════════════
            if has_real_data:
                total_time = max(time_data)
                # Use actual test_duration for x-axis if available
                _db_dur = test_data.get('test_duration')
                actual_total_time = int(_db_dur) if _db_dur else total_time
                
                # Phase boundary times from markers
                if t1_index is not None and t1_index < len(time_data):
                    ph1_end = time_data[t1_index]
                    idx1 = t1_index
                else:
                    ph1_end = t1_sec
                    idx1 = next((i for i, t in enumerate(time_data) if t >= ph1_end), len(time_data) // 4)
                
                if t2_index is not None and t2_index < len(time_data):
                    ph2_end = time_data[t2_index]
                    idx2 = t2_index
                else:
                    ph2_end = t1_sec + t2_sec
                    idx2 = next((i for i, t in enumerate(time_data) if t >= ph2_end), len(time_data) * 3 // 4)
                
                # Determine result
                db_result = test_data.get('test_result', '')
                if db_result in ('PASS', 'FAIL'):
                    test_passed = (db_result == 'PASS')
                else:
                    decay = pressure_data[0] - pressure_data[-1] if len(pressure_data) > 1 else 0
                    test_passed = decay <= p8_drop
                
                phase3_color = '#00AA00' if test_passed else '#FF0000'
                result_color = '#00AA00' if test_passed else '#FF0000'
                result_label = _t('pdf_graph_pass') if test_passed else _t('pdf_graph_fail')
                
                # ── Draw 3 colored line segments ──
                # Phase 1: Inflation (orange)
                seg1_end = min(idx1 + 1, len(time_data))
                ax1.plot(time_data[:seg1_end], pressure_data[:seg1_end],
                        color='#FF8C00', linewidth=2.5, label=f't₁ {_t("pdf_graph_phase1")}', zorder=5)
                
                # Phase 2: Stabilization (blue) — overlap 1 point for continuity
                seg2_start = max(idx1, 0)
                seg2_end = min(idx2 + 1, len(time_data))
                ax1.plot(time_data[seg2_start:seg2_end], pressure_data[seg2_start:seg2_end],
                        color='#0066CC', linewidth=2.5, label=f't₂ {_t("pdf_graph_phase2")}', zorder=5)
                
                # Phase 3: Measurement (green=PASS / red=FAIL)
                seg3_start = max(idx2, 0)
                ax1.plot(time_data[seg3_start:], pressure_data[seg3_start:],
                        color=phase3_color, linewidth=2.5, label=f't₃ {_t("pdf_graph_measurement")} ({result_label})', zorder=5)
                
                # ── Vertical phase separator lines ──
                ax1.axvline(x=ph1_end, color='#FF8C00', linestyle='--', linewidth=1.2, alpha=0.6, zorder=4)
                ax1.axvline(x=ph2_end, color='#0066CC', linestyle='--', linewidth=1.2, alpha=0.6, zorder=4)
                
                # ── Horizontal reference lines ──
                if esp_pass_limit is not None:
                    try:
                        limit_pressure = float(esp_pass_limit)
                    except (TypeError, ValueError):
                        limit_pressure = actual_p1 - p8_drop
                elif t2_index is not None and t2_index < len(pressure_data):
                    limit_pressure = pressure_data[t2_index] - p8_drop
                else:
                    limit_pressure = actual_p1 - p8_drop
                
                ax1.axhline(y=actual_p1, color='#666', linestyle='--', linewidth=1.5,
                           alpha=0.6, label=f'{_t("pdf_graph_target_pressure")}: {actual_p1:.0f} Pa', zorder=1)
                ax1.axhline(y=limit_pressure, color='#CC0000', linestyle=':', linewidth=1.5,
                           alpha=0.7, label=f'{_t("pdf_graph_pass_limit")}: {limit_pressure:.0f} Pa', zorder=1)
                
                # ── Phase duration labels ──
                y_mid = (max(pressure_data) + min(pressure_data)) / 2
                label_y = min(pressure_data) * 0.45 if min(pressure_data) > 0 else y_mid * 0.5
                
                # Calculate actual measured phase durations
                measured_t1 = ph1_end
                measured_t2 = ph2_end - ph1_end
                # Use actual test_duration from DB if available, fallback to sample count
                _dur_val = test_data.get('test_duration') or test_measurements.get('duration_sec', test_measurements.get('dur'))
                if _dur_val is not None:
                    measured_t3 = int(_dur_val) - (t2_index if t2_index is not None else idx2)
                else:
                    measured_t3 = len(pressure_data) - (t2_index if t2_index is not None else idx2)
                
                ax1.text(ph1_end / 2, label_y, f't₁\n{measured_t1:.0f}s',
                        ha='center', va='center', fontsize=10, fontweight='bold',
                        color='#FF8C00', bbox=dict(boxstyle='round,pad=0.3', 
                        facecolor='white', edgecolor='#FF8C00', alpha=0.9))
                ax1.text((ph1_end + ph2_end) / 2, label_y, f't₂\n{measured_t2:.0f}s',
                        ha='center', va='center', fontsize=10, fontweight='bold',
                        color='#0066CC', bbox=dict(boxstyle='round,pad=0.3',
                        facecolor='white', edgecolor='#0066CC', alpha=0.9))
                ax1.text((ph2_end + actual_total_time) / 2, label_y, f't₃\n{measured_t3:.0f}s',
                        ha='center', va='center', fontsize=10, fontweight='bold',
                        color=phase3_color, bbox=dict(boxstyle='round,pad=0.3',
                        facecolor='white', edgecolor=phase3_color, alpha=0.9))
                
                # ── Styling ──
                ax1.set_xlabel(_t('pdf_graph_time'), fontsize=11, fontweight='bold')
                ax1.set_ylabel(_t('pdf_graph_pressure'), fontsize=11, fontweight='bold')
                ax1.set_title(_t('pdf_graph_realtime_title'),
                             fontsize=13, fontweight='bold', pad=10, loc='left')
                ax1.text(1.0, 1.015, f'{_t("pdf_graph_result")}: {result_label}',
                        transform=ax1.transAxes, fontsize=12, fontweight='bold',
                        color=result_color, ha='right', va='bottom')
                ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
                ax1.legend(loc='upper center', bbox_to_anchor=(0.5, -0.12),
                          fontsize=8, framealpha=0.9, ncol=3, borderaxespad=0)
                ax1.set_xlim(-5, max(actual_total_time + 5, total_time + 5, 100))
                y_max1 = max(pressure_data) + 100
                y_min1 = -70
                ax1.set_ylim(y_min1, y_max1)
            else:
                # No real data — show message
                ax1.text(0.5, 0.5, _t('pdf_graph_no_pressure'),
                        ha='center', va='center', fontsize=14, color='#999',
                        transform=ax1.transAxes)
                ax1.set_title(_t('pdf_graph_realtime_title'),
                             fontsize=13, fontweight='bold', pad=10, loc='left')
            
            # ════════════════════════════════════════════════════════
            # ██  BOTTOM PANEL (ax2) — Theoretical recipe curve     ██
            # ════════════════════════════════════════════════════════
            recipe_total = t1_sec + t2_sec + t3_sec
            limit_p = p1_target - p8_drop
            
            # Phase 1: Inflation (exponential rise to p1_target over t1_sec)
            t1_pts = np.linspace(0, t1_sec, max(int(t1_sec * 5), 100))
            p1_vals = p1_target * (1 - np.exp(-3 * t1_pts / max(t1_sec, 1)))
            ax2.plot(t1_pts, p1_vals, color='#FF8C00', linewidth=2.5,
                    label=_t('pdf_graph_phase1_full'), zorder=3)
            
            # Phase 2: Stabilization (small oscillations around p1_target)
            t2_pts = np.linspace(t1_sec, t1_sec + t2_sec, max(int(t2_sec * 5), 100))
            pulse_freq = 5
            p2_vals = p1_target + p2_hyst * 0.3 * np.sin(pulse_freq * 2 * np.pi * (t2_pts - t1_sec) / max(t2_sec, 1))
            ax2.plot(t2_pts, p2_vals, color='#0066CC', linewidth=2,
                    label=_t('pdf_graph_phase2_full'), zorder=3)
            
            # Phase 3: Measurement — Pass & Fail scenarios
            t3_pts = np.linspace(t1_sec + t2_sec, recipe_total, max(int(t3_sec * 3), 100))
            decay_pass = p1_target - (p8_drop * 0.5) * (t3_pts - t1_sec - t2_sec) / max(t3_sec, 1)
            decay_fail = p1_target - (p8_drop * 2.5) * (t3_pts - t1_sec - t2_sec) / max(t3_sec, 1)
            
            ax2.plot(t3_pts, decay_pass, color='#00AA00', linewidth=2.5,
                    label=_t('pdf_graph_phase3_pass'), linestyle='-', zorder=3)
            ax2.plot(t3_pts, decay_fail, color='#FF0000', linewidth=2,
                    label=_t('pdf_graph_phase3_fail'), linestyle='--', alpha=0.7, zorder=2)
            
            # Vertical phase separators
            ax2.axvline(x=t1_sec, color='#999', linestyle='-.', linewidth=1, alpha=0.5)
            ax2.axvline(x=t1_sec + t2_sec, color='#999', linestyle='-.', linewidth=1, alpha=0.5)
            
            # Theoretical max time line (magenta dotted like image 2)
            ax2.axvline(x=recipe_total, color='#CC00CC', linestyle=':', linewidth=1.5,
                       alpha=0.7, label=f'{_t("pdf_graph_theoretical_max")}: {recipe_total}s')
            
            # Horizontal reference lines
            ax2.axhline(y=p1_target, color='#666', linestyle='--', linewidth=1.5,
                       alpha=0.6, label=f'P1: {p1_target:.0f} Pa', zorder=1)
            ax2.axhline(y=limit_p, color='#CC0000', linestyle=':', linewidth=1.5,
                       alpha=0.7, label=f'{_t("pdf_graph_pass_limit")}: {limit_p:.0f} Pa', zorder=1)
            
            # Phase labels with bbox — only recipe (theoretical) times
            label_y2 = p1_target * 0.5
            
            t1_label = f't₁\n{t1_sec}s'
            t2_label = f't₂\n{t2_sec}s'
            t3_label = f't₃\n{t3_sec}s'
            
            ax2.text(t1_sec / 2, label_y2, t1_label,
                    ha='center', va='center', fontsize=9, fontweight='bold',
                    color='#FF8C00', bbox=dict(boxstyle='round,pad=0.4',
                    facecolor='white', edgecolor='#FF8C00', alpha=0.9))
            ax2.text(t1_sec + t2_sec / 2, label_y2, t2_label,
                    ha='center', va='center', fontsize=9, fontweight='bold',
                    color='#0066CC', bbox=dict(boxstyle='round,pad=0.4',
                    facecolor='white', edgecolor='#0066CC', alpha=0.9))
            ax2.text(t1_sec + t2_sec + t3_sec / 2, label_y2, t3_label,
                    ha='center', va='center', fontsize=9, fontweight='bold',
                    color='#00AA00', bbox=dict(boxstyle='round,pad=0.4',
                    facecolor='white', edgecolor='#00AA00', alpha=0.9))
            
            # Styling
            ax2.set_xlabel(_t('pdf_graph_time'), fontsize=11, fontweight='bold')
            ax2.set_ylabel(_t('pdf_graph_pressure'), fontsize=11, fontweight='bold')
            
            # Title with recipe params only (theoretical)
            ax2.set_title(f'{_t("pdf_graph_recipe_title")}  —  t₁={t1_sec}s  t₂={t2_sec}s  t₃={t3_sec}s  '
                         f'P1={p1_target:.0f}Pa  P8={p8_drop:.0f}Pa',
                         fontsize=11, fontweight='bold', pad=10, loc='left')
            ax2.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
            ax2.legend(loc='upper center', bbox_to_anchor=(0.5, -0.22),
                      fontsize=8, framealpha=0.9, ncol=3, borderaxespad=0)
            ax2.set_xlim(-2, recipe_total + 15)
            ax2.set_ylim(min(-60, limit_p - 100), p1_target + 120)
            
            # ── Save ─────────────────────────────────────────────────
            plt.tight_layout(rect=[0, 0.05, 1, 1])
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png', dir=self.output_dir)
            graph_path = temp_file.name
            temp_file.close()
            
            plt.savefig(graph_path, bbox_inches='tight', facecolor='white', edgecolor='none')
            plt.close()
            
            return graph_path
            
        except Exception as e:
            _logger.error("Error generating test graph: %s", e, exc_info=True)
            return None
    
    def _generate_summary_graph(self, test_data: Dict[str, Any], test_measurements: Dict[str, Any]) -> str:
        """
        Generate a summary bar chart when time series data is not available
        """
        try:
            fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
            fig.patch.set_facecolor('white')
            
            # Prepare data for summary visualization
            categories = []
            values = []
            
            # Add pressure if available
            target_pressure = test_data.get('target_pressure')
            measured_pressure = test_measurements.get('final_pressure') or test_measurements.get('avg_pressure')
            
            if target_pressure or measured_pressure:
                if target_pressure:
                    categories.append('Target\nPressure')
                    values.append(target_pressure)
                if measured_pressure:
                    categories.append('Measured\nPressure')
                    values.append(measured_pressure)
            
            # Add temperature if available
            target_temp = test_data.get('target_temperature')
            measured_temp = test_measurements.get('final_temperature') or test_measurements.get('avg_temperature')
            
            if target_temp or measured_temp:
                if target_temp:
                    categories.append('Target\nTemp')
                    values.append(target_temp)
                if measured_temp:
                    categories.append('Measured\nTemp')
                    values.append(measured_temp)
            
            if categories and values:
                bars = ax.bar(categories, values, color=['#3B82F6', '#60A5FA', '#EF4444', '#F87171'][:len(categories)])
                ax.set_ylabel('Value', fontsize=11)
                ax.set_title('Test Parameters Summary', fontsize=13, fontweight='bold')
                ax.grid(True, alpha=0.3, axis='y')
                
                # Add value labels on bars
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{height:.1f}',
                           ha='center', va='bottom', fontsize=10, fontweight='bold')
            else:
                ax.text(0.5, 0.5, 'No test data available for visualization', 
                       ha='center', va='center', fontsize=12)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
            
            plt.tight_layout()
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png', dir=self.output_dir)
            graph_path = temp_file.name
            temp_file.close()
            
            plt.savefig(graph_path, bbox_inches='tight', facecolor='white', edgecolor='none')
            plt.close()
            
            return graph_path
            
        except Exception as e:
            _logger.error("Error generating summary graph: %s", e)
            return None
    
    def generate_test_report(self, test_data: Dict[str, Any], 
                            signatures: List[Dict[str, Any]],
                            company_name: str = None,
                            lang: str = 'tr') -> str:
        """
        Generate comprehensive test report
        
        Returns: Path to generated PDF file
        """
        # Dosya adı = sanitize(test_id) + record_id + dil eki.
        # record_id (DB primary key) her satır için tekildir; iki farklı
        # test_id aynı safe_id'ye düşse bile PDF dosyaları çakışmaz.
        # Cache YOK: her çağrı güncel veriyle yeniden üretilir — böylece
        # yeni imza / düzeltilmiş veri PDF'e anında yansır ve eski cached
        # bir dosya yanlışlıkla açılmaz.
        safe_id = re.sub(r'[:\\/*?"<>|]', '', str(test_data['test_id']))
        rid = test_data.get('id')
        rid_suffix = f"_{rid}" if rid is not None else ''
        lang_suffix = f"_{lang}" if lang != 'tr' else ''
        filename = f"{safe_id}{rid_suffix}{lang_suffix}.pdf"
        filepath = os.path.join(self.output_dir, filename)

        _t = lambda k: Translations.t(k, lang)
        
        doc = SimpleDocTemplate(filepath, pagesize=A4,
                                topMargin=0.7*inch, bottomMargin=0.6*inch,
                                leftMargin=40, rightMargin=30)
        story = []

        # Page callback stored for NumberedCanvas
        _test_id_for_cb = str(test_data.get('test_id', ''))
        company_name = company_name or self._company_name()
        _company_for_cb = company_name
        def _test_page_cb(canvas_obj, doc_obj):
            canvas_obj.saveState()
            w, h = A4
            # Header line
            canvas_obj.setFont(_FONT_BOLD, 8)
            canvas_obj.drawString(40, h - 30, _company_for_cb)
            canvas_obj.drawRightString(w - 40, h - 30, f"Test No: {_test_id_for_cb}")
            canvas_obj.setStrokeColor(colors.grey)
            canvas_obj.line(40, h - 35, w - 40, h - 35)
            # Footer line (sayfa numarası NumberedCanvas tarafından eklenir)
            canvas_obj.line(40, 38, w - 40, 38)
            canvas_obj.restoreState()

        # Logo
        try:
            logo_path = self._resolve_logo_path()
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=1.5*inch, height=0.75*inch)
                logo.hAlign = 'RIGHT'
                story.append(logo)
                story.append(Spacer(1, -0.75*inch)) # Negative spacer to overlap title slightly or align? 
                                                  # Actually better keep it simple:
        except Exception as e:
            _logger.warning("Logo load error in test report: %s", e)

        # Title
        story.append(Paragraph(f"{company_name}", self.styles['CustomTitle']))
        story.append(Paragraph(_t('pdf_test_report_title'), self.styles['CustomTitle']))
        story.append(Spacer(1, 0.15*inch))
        
        # Test Bilgileri
        story.append(Paragraph(_t('pdf_test_info_header'), self.styles['SectionHeader']))
        
        # Get operator name
        operator_name = 'N/A'
        operator_id = test_data.get('operator_id')
        if operator_id:
            try:
                conn = self.db.connect()
                cursor = conn.cursor()
                cursor.execute('SELECT full_name FROM users WHERE id = ?', (operator_id,))
                result = cursor.fetchone()
                if result:
                    operator_name = result['full_name']
                self.db.close()
            except Exception as e:
                _logger.debug("Operator DB lookup error: %s", e)
        # FIX #1 fallback: If DB lookup failed, try operator_name from data_json
        if operator_name == 'N/A':
            try:
                data_json = test_data.get('data_json', '{}')
                if isinstance(data_json, str):
                    parsed = json.loads(data_json)
                else:
                    parsed = data_json
                op_from_json = parsed.get('operator_name') or parsed.get('operator', '')
                if op_from_json:
                    operator_name = op_from_json
            except Exception as e:
                _logger.debug("Operator name fallback error: %s", e)
        
        # Extract device_id from data_json or test_data
        device_id_raw = ''
        parsed_dj = {}
        try:
            data_json_raw = test_data.get('data_json', '{}')
            if isinstance(data_json_raw, str):
                parsed_dj = json.loads(data_json_raw)
            else:
                parsed_dj = data_json_raw or {}
            device_id_raw = test_data.get('device_id') or parsed_dj.get('device_id') or ''
        except Exception as e:
            _logger.debug("device_id parse error: %s", e)
        # Fallback: test_id formatı "{device_id}-{seq:09d}" ise device_id'yi çıkar
        if not device_id_raw:
            tid = test_data.get('test_id', '')
            if tid and '-' in tid:
                prefix = tid.rsplit('-', 1)[0]
                if prefix and not prefix.startswith('GT_'):
                    device_id_raw = prefix
        # LCC_XXXXXXXX formatındaki device_id'den MAC adresini çöz
        device_id_display = self._decode_device_id_to_mac(device_id_raw) if device_id_raw else 'N/A'
        
        # Localized status/result maps
        _status_map = {
            'COMPLETED': _t('pdf_status_completed'),
            'RUNNING': _t('pdf_status_running'),
            'FAILED': _t('pdf_status_failed'),
            'ABORTED': _t('pdf_status_aborted'),
        }
        _result_map = {
            'PASS': _t('pdf_result_pass'),
            'FAIL': _t('pdf_result_fail'),
        }
        raw_status = test_data.get('test_status', 'N/A')
        raw_result = test_data.get('test_result', 'N/A')
        tr_status = _status_map.get(raw_status, raw_status)
        tr_result = _result_map.get(raw_result, raw_result)
        
        test_info = [
            [_t('pdf_device_sn'), device_id_display],
            [_t('pdf_test_no'), test_data.get('test_id', 'N/A')],
            [_t('pdf_port'), _decode_port_display(test_data.get('port_number') or parsed_dj.get('port', 'N/A'))],
            [_t('pdf_rfid'), test_data.get('glove_batch_number', 'N/A')],
            [_t('pdf_operator'), operator_name],
            [_t('pdf_test_start'), format_datetime_tr(test_data.get('test_start_time', 'N/A'))],
            [_t('pdf_test_status'), tr_status],
            [_t('pdf_test_result'), tr_result]
        ]
        
        # Sonuç satırı renk belirleme (grafikteki renklerle aynı: yeşil=#00AA00, kırmızı=#FF0000)
        result_row_idx = len(test_info) - 1  # Son satır
        result_fg = colors.HexColor('#00AA00') if raw_result == 'PASS' else (colors.HexColor('#FF0000') if raw_result == 'FAIL' else colors.black)
        
        info_table = Table(test_info, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8E8E8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), _FONT_BOLD),
            ('FONTNAME', (0, 0), (-1, -1), _FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (1, result_row_idx), (1, result_row_idx), result_fg),
            ('FONTNAME', (1, result_row_idx), (1, result_row_idx), _FONT_BOLD),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 0.15*inch))
        
        # Extract recipe_params from data_json (captured from ESP32 at TEST_STARTED)
        recipe_params_from_esp = None
        try:
            import json
            data_json = test_data.get('data_json', '{}')
            if isinstance(data_json, str):
                parsed_data = json.loads(data_json)
            else:
                parsed_data = data_json or {}
            recipe_params_from_esp = parsed_data.get('recipe_params')
        except Exception as e:
            _logger.debug("recipe_params parse error: %s", e)
        
        # Recipe Parameters — always from ESP32 captured data (recipe_params in data_json)
        # This is the single source of truth: captured at TEST_STARTED from the device
        rp = recipe_params_from_esp or {}
        recipe_name = rp.get('name') or test_data.get('glove_type', 'N/A')
        
        # Extract measured values from data_json for "Ölçülen" column
        measured = {}
        try:
            _dj = test_data.get('data_json', '{}')
            if isinstance(_dj, str):
                _pd = json.loads(_dj)
            else:
                _pd = _dj or {}
            
            t1 = _pd.get('t1_index')          # inflation end second
            t2 = _pd.get('t2_index')          # stabilization end second
            measured['p1'] = f"{t1}s" if t1 is not None else '-'
            measured['p2'] = f"{int(_pd['start_pressure'])}Pa" if 'start_pressure' in _pd and _pd['start_pressure'] else '-'
            measured['p3'] = f"{t2 - t1}s" if (t1 is not None and t2 is not None) else '-'
            measured['p4'] = '-'  # no measured value for reinflation threshold
            
            is_pass = (test_data.get('test_result', '') == 'PASS')
            wd = _pd.get('window_drop')
            td = _pd.get('total_drop')
            dur = _pd.get('duration_sec', _pd.get('dur'))
            
            measured['p6'] = f"{int(wd)}Pa" if (is_pass and wd is not None) else '-'
            _pr = _pd.get('pressure_readings', [])
            # Use actual test_duration from DB if available, fallback to data_json dur, then sample count
            _actual_dur = test_data.get('test_duration') or dur
            if _actual_dur is not None:
                measured_t3_sec = int(_actual_dur) - (t2 if t2 is not None else 0)
            else:
                measured_t3_sec = (len(_pr) - t2) if (t2 is not None and len(_pr) > 0 and t2 < len(_pr)) else None
            measured['p7'] = f"{int(measured_t3_sec)}s" if measured_t3_sec is not None else '-'
            measured['p8'] = f"{int(td)}Pa" if (is_pass and td is not None) else '-'
        except Exception as e:
            _logger.debug("Measured values parse error: %s", e)
            measured = {k: '-' for k in ('p1','p2','p3','p4','p6','p7','p8')}
        
        # Merged Recipe Table
        story.append(Paragraph(_t('pdf_recipe_params'), self.styles['SectionHeader']))
        
        recipe_table_data = [
            [_t('pdf_param_definition'), _t('pdf_target_value'), _t('pdf_actual_value')],
            [_t('pdf_recipe_name'), recipe_name, ''],
            [_t('pdf_p1_desc'), f"{rp.get('p1', 'N/A')}s", measured.get('p1', '-')],
            [_t('pdf_p2_desc'), f"{rp.get('p2', 'N/A')}Pa", measured.get('p2', '-')],
            [_t('pdf_p3_desc'), f"{rp.get('p3', 'N/A')}s", measured.get('p3', '-')],
            [_t('pdf_p4_desc'), f"{rp.get('p4', 'N/A')}Pa", measured.get('p4', '-')],
            [_t('pdf_p6_desc'), f"{rp.get('p6', 'N/A')}Pa", measured.get('p6', '-')],
            [_t('pdf_p7_desc'), f"{rp.get('p7', 'N/A')}s", measured.get('p7', '-')],
            [_t('pdf_p8_desc'), f"{rp.get('p8', 'N/A')}Pa", measured.get('p8', '-')],
        ]
        
        recipe_merged_table = Table(recipe_table_data, colWidths=[2.9*inch, 1.55*inch, 1.55*inch])
        recipe_merged_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), _FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#E8E8E8')),
            ('BACKGROUND', (0, 2), (-1, -1), colors.beige),
            ('SPAN', (1, 1), (2, 1)),
        ]))
        
        story.append(recipe_merged_table)
        story.append(Spacer(1, 0.15*inch))
        
        # Elektronik İmzalar (dijital — DB'den)
        if signatures:
            story.append(Paragraph(_t('pdf_electronic_sigs'), self.styles['SectionHeader']))
            
            sig_data = [[_t('pdf_sig_name'), _t('pdf_sig_meaning'), _t('pdf_sig_datetime')]]
            for sig in signatures:
                sig_data.append([
                    sig.get('full_name', 'N/A'),
                    sig.get('signature_meaning', 'N/A'),
                    format_datetime_tr(sig.get('signature_timestamp', 'N/A'))
                ])
            
            sig_table = Table(sig_data, colWidths=[2*inch, 2*inch, 2.5*inch])
            sig_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), _FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            
            story.append(sig_table)
            story.append(Spacer(1, 0.15*inch))
        
        # Veri Bütünlüğü kaldırıldı — sadece imza alanları kalacak
        
        # ── İmza Alanları (Uygulayan / Kontrol Eden / Onaylayan) ──
        story.append(Paragraph(_t('pdf_signatures'), self.styles['SectionHeader']))
        
        sig_fields_data = [
            ['', _t('pdf_sig_tester'), _t('pdf_sig_reviewer'), _t('pdf_sig_qa')],
            [_t('pdf_sig_fullname'), '', '', ''],
            [_t('pdf_sig_sign'), '', '', ''],
            [_t('pdf_sig_date'), '', '', ''],
        ]
        
        sig_fields_table = Table(sig_fields_data, colWidths=[1.0*inch, 1.5*inch, 1.3*inch, 2.2*inch])
        sig_fields_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Label column
            ('FONTNAME', (0, 1), (0, -1), _FONT_BOLD),
            ('FONTSIZE', (0, 1), (0, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#F0F0F0')),
            # Data cells — boş, elle doldurulacak, sola yaslı
            ('FONTNAME', (1, 1), (-1, -1), _FONT),
            ('FONTSIZE', (1, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'LEFT'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            # İmza satırı yüksekliği (elle imza atılabilsin)
            ('TOPPADDING', (1, 2), (-1, 2), 16),
            ('BOTTOMPADDING', (1, 2), (-1, 2), 16),
        ]))
        
        story.append(sig_fields_table)
        story.append(Spacer(1, 0.15*inch))
        
        # Footer
        footer_text = f"{_t('pdf_created_at')}: {now_tr()}<br/>"
        footer_text += _t('pdf_cfr_footer')
        story.append(Paragraph(footer_text, self.styles['Normal']))
        
        # ═══════════════════════════════════════════════════════════════
        # SAYFA 2 — Test Data Visualization
        # ═══════════════════════════════════════════════════════════════
        story.append(PageBreak())
        
        # Test Verisi Görselleştirme
        story.append(Paragraph(_t('pdf_graph_header'), self.styles['SectionHeader']))
        
        graph_path = self._generate_test_graph(test_data, lang=lang)
        if graph_path and os.path.exists(graph_path):
            try:
                graph_img = Image(graph_path, width=6.5*inch, height=7.2*inch)
                graph_img.hAlign = 'CENTER'
                story.append(graph_img)
            except Exception as e:
                _logger.warning("Error adding graph to PDF: %s", e)
                story.append(Paragraph(_t('pdf_graph_failed'), self.styles['Normal']))
        else:
            story.append(Paragraph(_t('pdf_graph_no_data'), self.styles['Normal']))
        
        
        # Build PDF — pass lang to NumberedCanvas
        doc.build(story, onFirstPage=_test_page_cb, onLaterPages=_test_page_cb,
                  canvasmaker=_make_numbered_canvas(lang))
        
        # Clean up temporary graph file
        if graph_path and os.path.exists(graph_path):
            try:
                os.remove(graph_path)
            except Exception:
                _logger.debug("Temp graph file cleanup failed")  # Non-critical
        
        return filepath
    
    def generate_audit_trail_report(self, audit_records: List[Dict[str, Any]],
                                   company_name: str = None,
                                   output_dir: str = None,
                                   lang: str = 'tr') -> str:
        """Generate audit trail report
        
        Args:
            audit_records: List of audit trail records
            company_name: Company name for header
            output_dir: Optional override for output directory (e.g. batch folder)
        """
        target_dir = output_dir or self.output_dir
        os.makedirs(target_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"audit_trail_{timestamp}.pdf"
        filepath = os.path.join(target_dir, filename)
        company_name = company_name or self._company_name()
        
        doc = SimpleDocTemplate(filepath, pagesize=A4)
        story = []
        
        # Logo — sağ kenarı sayfanın sağından 20 birim içeride
        try:
            logo_path = self._resolve_logo_path()
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=1.5*inch, height=0.75*inch)
                logo.hAlign = 'RIGHT'
                story.append(Spacer(1, -60))  # 60px yukarı
                from reportlab.platypus import Indenter
                story.append(Indenter(left=110, right=-52))  # sağ kenar: margin(72)-52=20
                story.append(logo)
                story.append(Indenter(left=-110, right=52))  # indent'i geri al
                story.append(Spacer(1, -0.75*inch))
        except Exception as e:
            _logger.warning("Logo load error in audit report: %s", e)

        _t = lambda k: Translations.t(k, lang)

        # Title (50px aşağı)
        story.append(Spacer(1, 50))
        story.append(Paragraph(f"{company_name}", self.styles['CustomTitle']))
        story.append(Paragraph(_t('pdf_audit_title'), self.styles['CustomTitle']))
        story.append(Spacer(1, 0.3*inch))
        
        # Audit Records
        story.append(Paragraph(f"{_t('pdf_audit_total')}: {len(audit_records)}", self.styles['SectionHeader']))
        
        if audit_records:
            # Create table with audit data
            # Use Paragraph for word wrapping in cells
            wrapped_style = ParagraphStyle(
                name='TableText',
                parent=self.styles['Normal'],
                fontSize=8,
                leading=10,
                alignment=TA_LEFT
            )
            
            audit_data = [['Timestamp', 'User', 'Action', 'Description']]
            
            # Define column widths
            col_widths = [1.3*inch, 1.2*inch, 1.3*inch, 3.5*inch] # Total ~7.3 inch (fits A4)

            # Faz-13: alarm satırları renkli — kritik KIRMIZI, uyarı turuncu.
            try:
                from core.alarm_codes import ALARM_CODES as _ACODES
            except Exception:
                _ACODES = {}
            crit_style = ParagraphStyle(
                name='TableTextCrit', parent=wrapped_style,
                textColor=colors.HexColor('#b91c1c'))
            warn_style = ParagraphStyle(
                name='TableTextWarn', parent=wrapped_style,
                textColor=colors.HexColor('#b45309'))

            for record in audit_records:
                _at = (record.get('action_type') or '').strip().upper()
                _sev = (_ACODES.get(_at) or ('', '', ''))[2]
                _st = (crit_style if _sev == 'crit'
                       else warn_style if _sev == 'warn'
                       else wrapped_style)
                audit_data.append([
                    Paragraph(format_datetime_tr(record.get('timestamp', 'N/A')), _st),
                    Paragraph(record.get('username', 'N/A'), _st),
                    Paragraph(record.get('action_type', 'N/A'), _st),
                    Paragraph(record.get('description', 'N/A'), _st)
                ])
            
            audit_table = Table(audit_data, colWidths=col_widths, repeatRows=1)
            audit_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), _FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            
            story.append(audit_table)
        
        # Build PDF
        doc.build(story, canvasmaker=_make_numbered_canvas(lang))
        
        return filepath
    # ═══════════════════════════════════════════════════════════════════
    # BATCH SUMMARY REPORT
    # ═══════════════════════════════════════════════════════════════════

    def generate_batch_summary_report(self, batch_data: Dict[str, Any],
                                       all_ports_dict: Dict[int, Dict] = None,
                                       company_name: str = None,
                                       include_fails: bool = True,
                                       lang: str = 'tr',
                                       audit_records: Optional[List[Dict[str, Any]]] = None,
                                       alarm_records: Optional[List[Dict[str, Any]]] = None,
                                       movement_records: Optional[List[Dict[str, Any]]] = None,
                                       filename_suffix: str = '',
                                       report_title: Optional[str] = None) -> str:
        """
        Batch özet raporu üretir.
        batch_data: get_active_batch() çıktısı (ports listesi dahil)
        all_ports_dict: {port_id: port_row_dict} — port adları için
        include_fails: False ise FAIL portlar için son testi (PASS/FAIL fark etmez) gösterir
        audit_records:   Batch aralığındaki denetim izi satırları (opsiyonel).
                         Verilirse Port Detayları öncesine "Denetim İzi Raporu"
                         tablosu eklenir.
        alarm_records:   Batch aralığındaki LAF alarm event satırları
                         (`laf_alarm_events`). Verilirse Sayfa 2'de "Alarm"
                         tablosu eklenir.
        movement_records: Batch aralığındaki eldiven portu / kapak hareketleri.
                         Her satır: {code, description, start, end}.
        filename_suffix: Dosya adına eklenecek ek (örn. '_ozet' — kompakt
                         alarm+port raporu aynı klasörde ayrı dosya olur).
        Returns: oluşturulan PDF dosya yolu
        """
        batch_name = batch_data.get('batch_name', 'Batch')
        safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in batch_name).strip()
        batch_dir = os.path.join(self.batch_output_dir, safe_name)
        os.makedirs(batch_dir, exist_ok=True)

        lang_suffix = f"_{lang}" if lang != 'tr' else ''
        filepath = os.path.join(
            batch_dir,
            f"BATCH_SUMMARY_{safe_name}{filename_suffix}{lang_suffix}.pdf")
        _t = lambda k: Translations.t(k, lang)
        company_name = company_name or self._company_name()
        doc = SimpleDocTemplate(filepath, pagesize=A4,
                                topMargin=0.7*inch, bottomMargin=0.6*inch)
        story = []

        # Page callback: Batch name header (sayfa numarası NumberedCanvas tarafından eklenir)
        _batch_name_cb = batch_name
        _company_cb = company_name
        def _batch_page_cb(canvas_obj, doc_obj):
            canvas_obj.saveState()
            w, h = A4
            # Header line
            canvas_obj.setFont(_FONT_BOLD, 8)
            canvas_obj.drawString(40, h - 30, _company_cb)
            canvas_obj.drawRightString(w - 40, h - 30, f"Batch: {_batch_name_cb}")
            canvas_obj.setStrokeColor(colors.grey)
            canvas_obj.line(40, h - 35, w - 40, h - 35)
            # Footer line
            canvas_obj.line(40, 38, w - 40, 38)
            canvas_obj.restoreState()

        # Logo
        try:
            logo_path = self._resolve_logo_path()
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=1.5 * inch, height=0.75 * inch)
                logo.hAlign = 'RIGHT'
                story.append(logo)
        except Exception as e:
            _logger.warning("Logo load error in batch report: %s", e)

        # Title — başlık önceliği: çağrıdan gelen override (özet rapor)
        # → Ayarlar'daki 'report_batch_title' (2026-08-05; önceden sabit
        # çeviri kullanılıyordu ve ayar hiç yansımıyordu).
        story.append(Paragraph(f"{company_name}", self.styles['CustomTitle']))
        story.append(Paragraph(report_title or self._batch_report_title(),
                               self.styles['CustomTitle']))
        story.append(Spacer(1, 0.2 * inch))

        # Batch info
        _batch_status_map = {
            'COMPLETED': _t('pdf_batch_completed'),
            'IN_PROGRESS': _t('pdf_batch_in_progress'),
            'PENDING': _t('pdf_batch_pending'),
        }
        # Toplam süre (başlangıç → bitiş) — müşteri isteği 2026-08-06:
        # çalışma zamanı özeti satırı (HH:MM:SS + toplam saat).
        _dur_txt = '-'
        try:
            _st_raw = batch_data.get('start_time')
            _et_raw = batch_data.get('end_time')
            if _st_raw and _et_raw and str(_et_raw) not in ('-', 'None'):
                _fmts = ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                         '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S')

                def _parse_ts(v):
                    s = str(v).strip()
                    try:
                        return datetime.fromisoformat(s)
                    except ValueError:
                        for f in _fmts:
                            try:
                                return datetime.strptime(s, f)
                            except ValueError:
                                pass
                    return None

                _d1, _d2 = _parse_ts(_st_raw), _parse_ts(_et_raw)
                if _d1 and _d2 and _d2 >= _d1:
                    _secs = int((_d2 - _d1).total_seconds())
                    _dur_txt = (f"{_secs // 3600:02d}:"
                                f"{(_secs % 3600) // 60:02d}:"
                                f"{_secs % 60:02d}")
                    _hours = _secs / 3600.0
                    _dur_txt += (f"  ({_hours:.2f} saat)" if lang == 'tr'
                                 else f"  ({_hours:.2f} h)")
        except Exception:
            _dur_txt = '-'
        _dur_label = 'Toplam Süre' if lang == 'tr' else 'Total Duration'
        # Durum satırı: port sonuç özeti eklenir — "Tamamlandı (13/13 PASS)".
        _status_raw = batch_data.get('status', '-')
        _status_txt = _batch_status_map.get(_status_raw, _status_raw)
        _ports_for_cnt = batch_data.get('ports') or []
        if _ports_for_cnt:
            _n_total = len(_ports_for_cnt)
            _n_pass = sum(1 for p in _ports_for_cnt
                          if str(p.get('status', '')).upper() == 'PASS')
            _status_txt = f"{_status_txt} ({_n_pass}/{_n_total} PASS)"
        info_data = [
            [_t('pdf_batch_name'), batch_name],
            [_t('pdf_batch_start'), format_datetime_tr(batch_data.get('start_time', '-'))],
            [_t('pdf_batch_end'), format_datetime_tr(batch_data.get('end_time', '-'))],
            [_dur_label, _dur_txt],
            [_t('pdf_batch_status'), _status_txt],
        ]
        info_table = Table(info_data, colWidths=[2 * inch, 4 * inch])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), _FONT_BOLD),
            ('FONTNAME', (1, 0), (1, -1), _FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.3 * inch))

        # ── Denetim İzi Raporu / Audit Trail Report ─────────────────
        # Batch aralığındaki audit satırları (opsiyonel).
        if audit_records:
            story.append(Paragraph(_t('pdf_audit_title'), self.styles['SectionHeader']))
            story.append(Paragraph(
                f"{_t('pdf_audit_total')}: {len(audit_records)}",
                ParagraphStyle('BatchAuditCount', fontName=_FONT_BOLD, fontSize=10,
                               textColor=colors.HexColor('#1F2937'))
            ))
            _a_hdr = ParagraphStyle('BatchAuditHdr', fontName=_FONT_BOLD, fontSize=7,
                                    leading=9, textColor=colors.whitesmoke,
                                    wordWrap='CJK')
            _a_cell = ParagraphStyle('BatchAuditCell', fontName=_FONT, fontSize=7,
                                     leading=9, wordWrap='CJK')
            audit_rows = [[
                Paragraph('Timestamp', _a_hdr),
                Paragraph('User', _a_hdr),
                Paragraph('Action', _a_hdr),
                Paragraph('Description', _a_hdr),
            ]]
            for rec in audit_records:
                audit_rows.append([
                    Paragraph(format_datetime_tr(rec.get('timestamp', '')), _a_cell),
                    Paragraph(str(rec.get('username') or rec.get('user') or ''), _a_cell),
                    Paragraph(str(rec.get('action_type') or ''), _a_cell),
                    Paragraph(str(rec.get('description') or ''), _a_cell),
                ])
            audit_table = Table(audit_rows,
                                colWidths=[1.2 * inch, 0.8 * inch, 1.4 * inch, 3.9 * inch],
                                repeatRows=1)
            audit_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), _FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(audit_table)
            story.append(Spacer(1, 0.3 * inch))

        # Port table header
        story.append(Paragraph(_t('pdf_batch_port_details'), self.styles['SectionHeader']))

        _hdr_style = ParagraphStyle('BatchHdrWrap', fontName=_FONT_BOLD, fontSize=7, leading=9,
                                      textColor=colors.whitesmoke, wordWrap='CJK')
        header = [Paragraph(h, _hdr_style) for h in
                  ["#", _t('pdf_batch_col_port'), _t('pdf_batch_col_rfid'), _t('pdf_batch_col_test_id'),
                   _t('pdf_batch_col_operator'), _t('pdf_batch_col_date'), _t('pdf_batch_col_recipe'),
                   _t('pdf_batch_col_result'), _t('pdf_batch_col_desc')]]
        rows = [header]

        all_ports_dict = all_ports_dict or {}
        ports = batch_data.get('ports', [])

        for idx, p in enumerate(ports, 1):
            port_id = p.get('port_id', 0)
            port_info = all_ports_dict.get(port_id, {})
            port_name = port_info.get('name', f"Port {port_id}")
            rfid = p.get('rfid_tag', '')
            status = p.get('status', 'PENDING')

            # Fetch test_id, operator, date, recipe from test_records if linked
            test_id_str = '-'
            operator_str = '-'
            test_date_str = '-'
            recipe_str = '-'
            _port_result_map = {'PASS': _t('pdf_batch_pass'), 'FAIL': _t('pdf_batch_fail'), 'PENDING': _t('pdf_batch_not_tested')}
            result_str = _port_result_map.get(status, status)

            # include_fails=False ve port FAIL ise: batch'teki FAIL test yerine
            # o port'un son testini göster (RFID'ye göre)
            lookup_record_id = p.get('test_record_id')
            if not include_fails and status == 'FAIL' and rfid:
                try:
                    conn = self.db.connect()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, test_id, test_result, test_start_time,
                               glove_type, data_json
                        FROM test_records
                        WHERE glove_batch_number = ?
                        ORDER BY test_start_time DESC
                        LIMIT 1
                    """, (rfid,))
                    last_row = cur.fetchone()
                    self.db.close()
                    if last_row:
                        lookup_record_id = last_row[0]
                except Exception:
                    _logger.debug("FAIL→last test lookup failed for rfid %s", rfid)

            if lookup_record_id:
                try:
                    conn = self.db.connect()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT tr.test_id, tr.test_result, tr.test_start_time,
                               u.full_name, tr.data_json, tr.glove_type
                        FROM test_records tr
                        LEFT JOIN users u ON tr.operator_id = u.id
                        WHERE tr.id = ?
                    """, (lookup_record_id,))
                    row = cur.fetchone()
                    self.db.close()
                    if row:
                        test_id_str = row[0] if row[0] else '-'
                        _r = row[1] if row[1] else status
                        result_str = {'PASS': _t('pdf_batch_pass'), 'FAIL': _t('pdf_batch_fail')}.get(_r, _r)
                        test_date_str = format_datetime_tr(row[2]) if row[2] else '-'
                        operator_str = row[3] if row[3] else '-'
                        # ESP'den gelen reçete: data_json → recipe_params.name veya glove_type
                        try:
                            import json as _json
                            dj = _json.loads(row[4]) if row[4] else {}
                            rp = dj.get('recipe_params', {})
                            recipe_str = rp.get('name') or row[5] or '-'
                        except Exception as e:
                            _logger.debug("Recipe parse error in batch row: %s", e)
                            recipe_str = row[5] if row[5] else '-'
                except Exception as e:
                    _logger.debug("Batch port DB lookup error: %s", e)

            explanation = p.get('explanation', '') or ''
            # Wrap ALL cells in Paragraph for auto line-break (prevent overflow)
            # None-safe: reportlab Paragraph None kabul etmez.
            _cw = ParagraphStyle('BatchCellWrap', fontName=_FONT, fontSize=7, leading=9, wordWrap='CJK')
            _cwb = ParagraphStyle('BatchCellWrapBold', fontName=_FONT_BOLD, fontSize=7, leading=9, wordWrap='CJK')
            rows.append([
                Paragraph(str(idx), _cw),
                Paragraph(str(port_name or '-'), _cw),
                Paragraph(str(rfid or '-'), _cw),
                Paragraph(str(test_id_str or '-'), _cw),
                Paragraph(str(operator_str or '-'), _cw),
                Paragraph(str(test_date_str or '-'), _cw),
                Paragraph(str(recipe_str or '-'), _cw),
                Paragraph(str(result_str or '-'), _cwb),
                Paragraph(str(explanation or ''), _cw),
            ])

        col_widths = [0.3*inch, 0.55*inch, 0.85*inch, 0.95*inch, 0.8*inch, 0.95*inch, 0.75*inch, 0.65*inch, 1.5*inch]
        port_table = Table(rows, colWidths=col_widths, repeatRows=1)

        # Color coding per status
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), _FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        for row_idx, p in enumerate(ports, 1):
            s = p.get('status', 'PENDING')
            if s == 'PASS':
                style_cmds.append(('BACKGROUND', (7, row_idx), (7, row_idx), colors.HexColor('#D1FAE5')))
            elif s == 'FAIL':
                style_cmds.append(('BACKGROUND', (7, row_idx), (7, row_idx), colors.HexColor('#FEE2E2')))
            elif s == 'PENDING':
                style_cmds.append(('BACKGROUND', (7, row_idx), (7, row_idx), colors.HexColor('#FEF3C7')))

        port_table.setStyle(TableStyle(style_cmds))
        story.append(port_table)

        # Summary counts
        story.append(Spacer(1, 0.3 * inch))
        total = len(ports)
        passed = sum(1 for p in ports if p.get('status') == 'PASS')
        failed = sum(1 for p in ports if p.get('status') == 'FAIL')
        pending = sum(1 for p in ports if p.get('status') == 'PENDING')
        summary_text = (f"{_t('pdf_batch_total')}: {total} {_t('pdf_batch_port_unit')}  |  "
                        f"{_t('pdf_batch_passed')}: {passed}  |  {_t('pdf_batch_failed')}: {failed}  |  {_t('pdf_batch_untested')}: {pending}")
        story.append(Paragraph(summary_text, ParagraphStyle(
            'BatchSummary', fontName=_FONT_BOLD, fontSize=11,
            textColor=colors.HexColor('#1F2937'), alignment=TA_CENTER
        )))

        # ── Alarm + Hareket bölümleri (Sayfa 2) ──────────────────────
        if alarm_records is not None or movement_records is not None:
            story.append(PageBreak())

        _mv_hdr = ParagraphStyle('SecHdr', fontName=_FONT_BOLD, fontSize=8,
                                 leading=10, textColor=colors.whitesmoke,
                                 wordWrap='CJK')
        _mv_cell = ParagraphStyle('SecCell', fontName=_FONT, fontSize=8,
                                  leading=10, wordWrap='CJK')

        def _section_table(rows):
            """Ortak stil için helper."""
            tbl = Table(rows,
                        colWidths=[0.4*inch, 1.0*inch, 3.1*inch, 1.4*inch, 1.4*inch],
                        repeatRows=1)
            tbl.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), _FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            return tbl

        # Alarm tablosu
        if alarm_records is not None:
            story.append(Paragraph("Alarm", self.styles['SectionHeader']))
            alarm_rows = [[
                Paragraph('#', _mv_hdr),
                Paragraph('Alarm Code', _mv_hdr),
                Paragraph('Alarm Açıklama / Alarm Description', _mv_hdr),
                Paragraph('Başlangıç / Start', _mv_hdr),
                Paragraph('Bitiş / End', _mv_hdr),
            ]]
            if alarm_records:
                for i, a in enumerate(alarm_records, 1):
                    start = a.get('timestamp') or a.get('start') or ''
                    end = a.get('cleared_at') or a.get('end') or ''
                    alarm_rows.append([
                        Paragraph(str(i), _mv_cell),
                        Paragraph(str(a.get('flag_code') or a.get('code') or '-'), _mv_cell),
                        Paragraph(str(a.get('message') or a.get('description') or '-'), _mv_cell),
                        Paragraph(format_datetime_tr(start) if start else '-', _mv_cell),
                        Paragraph(format_datetime_tr(end) if end else '-', _mv_cell),
                    ])
            else:
                alarm_rows.append([
                    Paragraph('-', _mv_cell), Paragraph('-', _mv_cell),
                    Paragraph('Bu batch süresinde alarm yok / No alarm during this batch',
                              _mv_cell),
                    Paragraph('-', _mv_cell), Paragraph('-', _mv_cell),
                ])
            story.append(_section_table(alarm_rows))
            story.append(Spacer(1, 0.25 * inch))

        # Eldiven Port Hareketleri tablosu (yalnız hareket sensörü —
        # kapak olayları denetim izinde listelenir, 2026-08-03)
        if movement_records is not None:
            story.append(Paragraph(
                "Eldiven Port Hareketleri / Glove Port Movements",
                self.styles['SectionHeader']))
            move_rows = [[
                Paragraph('#', _mv_hdr),
                Paragraph('Action Code', _mv_hdr),
                Paragraph('Alarm Açıklama / Alarm Description', _mv_hdr),
                Paragraph('Başlangıç / Start', _mv_hdr),
                Paragraph('Bitiş / End', _mv_hdr),
            ]]
            if movement_records:
                for i, m in enumerate(movement_records, 1):
                    move_rows.append([
                        Paragraph(str(i), _mv_cell),
                        Paragraph(str(m.get('code') or '-'), _mv_cell),
                        Paragraph(str(m.get('description') or '-'), _mv_cell),
                        Paragraph(format_datetime_tr(m.get('start', '')) if m.get('start') else '-', _mv_cell),
                        Paragraph(format_datetime_tr(m.get('end', '')) if m.get('end') else '-', _mv_cell),
                    ])
            else:
                move_rows.append([
                    Paragraph('-', _mv_cell), Paragraph('-', _mv_cell),
                    Paragraph('Bu batch süresinde hareket yok / No movement during this batch',
                              _mv_cell),
                    Paragraph('-', _mv_cell), Paragraph('-', _mv_cell),
                ])
            story.append(_section_table(move_rows))
            story.append(Spacer(1, 0.25 * inch))

        # ── İmza Alanları ──
        story.append(Paragraph(_t('pdf_signatures'), self.styles['SectionHeader']))

        sig_fields_data = [
            ['', _t('pdf_sig_tester'), _t('pdf_sig_reviewer'), _t('pdf_sig_qa')],
            [_t('pdf_sig_fullname'), '', '', ''],
            [_t('pdf_sig_sign'), '', '', ''],
            [_t('pdf_sig_date'), '', '', ''],
        ]

        sig_fields_table = Table(sig_fields_data, colWidths=[1.0 * inch, 1.5 * inch, 1.3 * inch, 2.2 * inch])
        sig_fields_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Label column
            ('FONTNAME', (0, 1), (0, -1), _FONT_BOLD),
            ('FONTSIZE', (0, 1), (0, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#F0F0F0')),
            # Data cells
            ('FONTNAME', (1, 1), (-1, -1), _FONT),
            ('FONTSIZE', (1, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'LEFT'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            # İmza satırı yüksekliği
            ('TOPPADDING', (1, 2), (-1, 2), 16),
            ('BOTTOMPADDING', (1, 2), (-1, 2), 16),
        ]))

        story.append(sig_fields_table)
        story.append(Spacer(1, 0.15 * inch))

        # Footer
        story.append(Spacer(1, 0.3 * inch))
        footer_text = f"{_t('pdf_created_at')}: {now_tr()}<br/>"
        footer_text += _t('pdf_cfr_footer')
        story.append(Paragraph(footer_text, ParagraphStyle(
            'BatchFooter', fontName=_FONT, fontSize=8,
            textColor=colors.grey, alignment=TA_CENTER
        )))

        doc.build(story, onFirstPage=_batch_page_cb, onLaterPages=_batch_page_cb,
                  canvasmaker=_make_numbered_canvas(lang))
        return filepath