"""oRABS Interlock Matrisi — GMP maddesi + mevcut yazılım (GLT4.3/ORAPS) eşlemesi.

Komut: python _gen_interlock_matrix_xlsx.py
Çıktı: oRABS_Interlock_Matrisi.xlsx (bu dizinde)

Not: Bu matris canlı bir dokümandır. Yazılımda ORAPS/Weidmüller/LAF/Bariyer
tarafında yapılan her değişiklik sonrası gözden geçirilip güncellenmelidir.
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEADER_FILL = PatternFill('solid', fgColor='1F2937')
HEADER_FONT = Font(bold=True, color='FFFFFF', size=11)

DURUM_FILL = {
    'Uygulanmış':          PatternFill('solid', fgColor='D1FAE5'),
    'Kısmi':               PatternFill('solid', fgColor='FEF3C7'),
    'Uygulanmamış (Boşluk)': PatternFill('solid', fgColor='FEE2E2'),
    'N/A (Prosedür)':      PatternFill('solid', fgColor='DBEAFE'),
}
KRITIK_FILL = {
    'Kritik':      PatternFill('solid', fgColor='FEE2E2'),
    'Non-kritik':  PatternFill('solid', fgColor='E5E7EB'),
}
THIN = Side(style='thin', color='D1D5DB')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HEADERS = [
    'No', 'Interlock / Fonksiyon Adı', 'GMP Madde Referansı (özet)',
    'Yazılımdaki Karşılığı (dosya / modül)', 'Tetikleyen Koşul (Girdi)',
    'Permissive / İzin Koşulu', 'Etki (Çıkış / Aksiyon)',
    'Alarm / Uyarı (görsel-sesli)', 'Zaman Gecikmesi',
    'Bypass / Override', 'Fail-Safe Davranışı (elektrik kesintisi/restart)',
    'GMP Kritiklik', 'Mevcut Durum', 'Kalifikasyon (IQ/OQ)', 'Notlar',
]

ROWS = [
    dict(
        no=1,
        ad='Kapı Grubu Kilitleme (Batch Door Lock)',
        madde='oRABS\'e erişim sağlayan kapılar interlock edilmeli',
        yazilim='core/batch_manager.py (batch_door_config) + '
                'core/weidmuller_bridge.py (DO_LOCKED=0/DO_OPEN=1)',
        tetik='Aktif batch başlatma / config seçimi',
        permissive='Batch durumu "running"; config admin/supervisor '
                   'tarafından önceden tanımlanmış olmalı',
        etki='Kapı grubu DO=1 (kilitli) / DO=0 (açık)',
        alarm='Yok — sadece 3D görsel renklendirme',
        gecikme='Yok',
        bypass='Config değişikliği admin/supervisor; DO manuel toggle IO '
               'panelinden admin-only',
        failsafe='Bağlantı koptuğunda/yeniden kurulduğunda ~2 sn içinde '
                 'reconcile edilir (hedef state\'e çekilir)',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='Kapı grupları arası KARŞILIKLI ENGELLEME yok (bkz. Satır 2)',
    ),
    dict(
        no=2,
        ad='Karşılıklı Kapı / Transfer-Lock Interlock',
        madde='Karşılıklı kapıların aynı anda açılmasını önleyecek şekilde '
              'interlock edilmeli',
        yazilim='YOK — batch_door_config yalnız statik açık/kilitli seti '
                'tanımlıyor, gruplar arası ilişki modellenmiyor',
        tetik='—',
        permissive='—',
        etki='—',
        alarm='—',
        gecikme='—',
        bypass='—',
        failsafe='—',
        kritik='Kritik',
        durum='Uygulanmamış (Boşluk)',
        kalifikasyon='',
        not_='Öneri: door_group\'lara "mutually_exclusive_with" ilişkisi '
             'eklenip bir grup açıkken karşı grup otomatik kilitlenmeli; '
             'ihlalde alarm + audit üretilmeli.',
    ),
    dict(
        no=3,
        ad='Işık Bariyeri (Light Barrier) İzleme/İnterlock',
        madde='Gerekli çevresel koşulları bozabilecek şartlarda kapı '
              'açılmasını önleyecek şekilde interlock',
        yazilim='core/weidmuller_bridge.py (_on_di_edge, '
                'barrier_event_recorded) + light_barriers tablosu',
        tetik='DI kanalı (bariyer sensörü) BROKEN/CLEARED kenar geçişi',
        permissive='Bariyer is_active=1 ve en az bir kapıya bağlı olmalı',
        etki='Bağlı kapı(lar) 3D\'de turuncu + audit ORAPS_PORT_MOTION/'
             'barrier event; kapıyı FİZİKSEL olarak kilitlemiyor',
        alarm='Görsel (turuncu boyama + alarm banner); sesli YOK',
        gecikme='Yok',
        bypass='is_active toggle admin/supervisor (batch_manager)',
        failsafe='Bağlantı koparsa cache temizlenir; yeniden bağlanınca '
                 'reconcile',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='GMP maddesi "kapı açılmasını önleyecek" diyor; yazılım şu an '
             'sadece durumu bildiriyor, fiziksel engelleme yapmıyor.',
    ),
    dict(
        no=4,
        ad='Kablosuz IR Bariyer Sensörü (Port Hareketi İzleme)',
        madde='Rutin operasyon/müdahaleler sırasında kontaminasyon riskinin '
              'minimize edilmesi',
        yazilim='core/barrier_listener.py (E1/E0 mesajları) + port motion '
                'cache (overview_panel.py)',
        tetik='ESP-NOW master üzerinden E1 (bloke) / E0 (serbest) mesajı',
        permissive='—',
        etki='İlgili port 3D\'de mavi + audit ORAPS_PORT_MOTION',
        alarm='Görsel (mavi boyama); sesli YOK',
        gecikme='barrier_motion_hold_ms sonra otomatik temizlenir',
        bypass='Yok',
        failsafe='COM portu koparsa "bulunamadı" durumu + 3 sn periyodik '
                 'retry',
        kritik='Non-kritik',
        durum='Uygulanmış',
        kalifikasyon='',
        not_='İzleme amaçlı; gerçek bir interlock/engelleme değil.',
    ),
    dict(
        no=5,
        ad='Machine-Stop Idle Interlock (ORABS dışı makine durdurma)',
        madde='Interlock mantığı; oRABS operasyonel durumu ve makinenin '
              'çalışma modu dikkate alınarak oluşturulmalı',
        yazilim='core/weidmuller_bridge.py (_update_machine_stop_dos, '
                'MS_DO_STOP=1/MS_DO_RUN=0) + ayar oraps_machine_stop_idle',
        tetik='ORABS batch durumu ≠ "running" (idle/finished) veya GLT '
              'aşaması aktif',
        permissive='oraps_machine_stop_idle=1 olmalı — VARSAYILAN KAPALI (0)',
        etki='machine_stop rolündeki tüm DO\'lara sürekli DO=1 (DUR) '
             'yazılır',
        alarm='Yok — sessiz arka plan mekanizması',
        gecikme='Periyodik reconcile ~2 sn',
        bypass='Ayarın kendisi fiili bir override\'dır; Admin/Supervisor '
               'açar/kapar, audit\'e SETTINGS_CHANGED düşer',
        failsafe='Bağlantı yeniden kurulunca çıkış cache\'i temizlenir → '
                 'DO yeniden zorlanır',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='GMP gereği bu korumanın VARSAYILAN AÇIK olması ve kapatmanın '
             'gerekçe + audit ile sınırlı, yetkili personele özel olması '
             'önerilir (mevcut halde varsayılan kapalı).',
    ),
    dict(
        no=6,
        ad='Acil Stop (E-Stop)',
        madde='Kritik bir yardımcı sistemin kaybı sonrasında fail-safe '
              'duruma geçilmeli',
        yazilim='weidmuller_manager.py link_type=\'estop\' + '
                'estop_triggered sinyali + buzzer OR mantığı',
        tetik='DI (estop) = 1',
        permissive='—',
        etki='Buzzer DO aktif + alarm banner',
        alarm='Sesli (buzzer DO) + görsel banner',
        gecikme='Yok',
        bypass='Yok',
        failsafe='Yazılım yalnızca bildirim/log yapar; gerçek acil '
                 'durdurma devresinin PC/yazılımdan BAĞIMSIZ olması '
                 'gerekir (donanımsal doğrulanmalı)',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='Kalifikasyonda doğrulanmalı: e-stop fiziksel devresi PC/'
             'yazılım çökse dahi makineyi durdurabiliyor mu?',
    ),
    dict(
        no=7,
        ad='LAF Alarm Eşiği (kritik basınç/hava akışı)',
        madde='Hava akışı/havalandırma durumu, kritik basınç koşulları '
              'dikkate alınmalı',
        yazilim='core/laf_manager.py (low_alarm/high_alarm) + '
                'weidmuller_bridge.ai_alarm sinyali + overview banner',
        tetik='AI (analog giriş) değeri tanımlı eşik dışına çıkınca',
        permissive='—',
        etki='Banner + audit; MAKİNEYİ OTOMATİK DURDURMUYOR',
        alarm='Görsel banner (session-lokal "Tamam" ile kapanır); sesli '
              'YOK',
        gecikme='Yok (poll aralığında anlık)',
        bypass='Yok',
        failsafe='Sensör/bağlantı koparsa okuma "—" gösterilir, alarm '
                 'TETİKLENMEZ (sessiz hata riski)',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='GMP maddesi kritik basınç için proses durdurma bekliyor; şu '
             'an sadece bilgilendirme var. Öneri: LAF kritik alarmı ile '
             'machine_stop rölesi ilişkilendirilmeli.',
    ),
    dict(
        no=8,
        ad='Genel Alarm/Uyarı Banner + Buzzer',
        madde='Güvenli kapı açılmasına izin vermeyen durumda operatöre '
              'görsel ve/veya sesli uyarı verilmeli',
        yazilim='oraps/overview_panel.py (alarm_banner, _toggle_alarm_blink)'
                ' + buzzer DO (estop OR alarm)',
        tetik='Kritik audit olayı veya aktif LAF alarmı',
        permissive='—',
        etki='Kırmızı yanıp sönen banner + "✓ Tamam" onayı; buzzer DO',
        alarm='Görsel + sesli (buzzer donanıma bağlı)',
        gecikme='600 ms blink aralığı',
        bypass='Operatör "Tamam" ile session-lokal onaylar (tekrar '
               'tetiklenirse tekrar görünür)',
        failsafe='—',
        kritik='Kritik',
        durum='Uygulanmış',
        kalifikasyon='',
        not_='"Tamam" onayının audit\'e (ALARM_ACKED) düştüğü ayrıca '
             'doğrulanmalı.',
    ),
    dict(
        no=9,
        ad='IO Bağlantı Kaybı / Fail-Safe Reconcile',
        madde='Elektrik kesintisi, yeniden başlatma veya kritik yardımcı '
              'sistem kaybı sonrası önceden tanımlı fail-safe duruma '
              'geçilmeli',
        yazilim='core/weidmuller_bridge.py (connection_status, '
                '_seeded_modules/_connected_modules, start_all/stop_all)',
        tetik='Modbus TCP bağlantısının kopması/yeniden kurulması',
        permissive='—',
        etki='Kopunca: bayat DI cache\'i temizlenir; yeniden bağlanınca '
             'machine_stop DO\'ları ve kapı durumları reconcile edilir',
        alarm='Bağlantı durumu LED\'i (status bar)',
        gecikme='~2 sn periyodik reconcile',
        bypass='Yok',
        failsafe='KISMİ — DO\'ların fiziksel son durumu coupler\'da kalır; '
                 'batch ortasında PC/yazılım çökerse DO\'lar "donuk" '
                 'kalabilir, otomatik güvenli duruma geçiş garantisi yok',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='Batch ortasında elektrik kesintisi/PC restart senaryosu '
             'kalifikasyonda özellikle test edilmeli (IQ/OQ).',
    ),
    dict(
        no=10,
        ad='Admin Manuel DO Override (IO Paneli)',
        madde='Bypass/override fonksiyonu yalnızca yetkilendirilmiş '
              'personele açık olmalı, alarm ve/veya kayıt oluşturmalı',
        yazilim='oraps/io_panel.py (_DoCell manuel toggle) → '
                'weidmuller_manager.log_write → audit IO_WRITE',
        tetik='Admin\'in IO panelinden manuel DO tıklaması',
        permissive='Sadece Admin (IO paneli admin-only)',
        etki='Herhangi bir DO (kapı kilidi/machine_stop dahil) manuel set '
             'edilir',
        alarm='Yok — yalnızca audit log (IO_WRITE)',
        gecikme='—',
        bypass='Bu fonksiyonun kendisi override\'dır: admin-only + audit '
               'var',
        failsafe='—',
        kritik='Kritik',
        durum='Kısmi',
        kalifikasyon='',
        not_='GMP maddesi override için "dokümante edilmiş risk '
             'değerlendirmesi" istiyor; yazılımda override sırasında '
             'zorunlu gerekçe/açıklama alanı YOK. Ayrıca görsel "override '
             'aktif" uyarısı yok.',
    ),
    dict(
        no=11,
        ad='Interlock Matrisi Kalifikasyonu (genel)',
        madde='GMP/proses güvenliği açısından kritik tüm interlocklar bir '
              'Interlock Matrisi\'nde tanımlanmalı ve kalifikasyon '
              'çalışmalarıyla doğrulanmalı',
        yazilim='N/A — prosedür/dokümantasyon gereksinimi',
        tetik='—',
        permissive='—',
        etki='—',
        alarm='—',
        gecikme='—',
        bypass='—',
        failsafe='—',
        kritik='Kritik',
        durum='N/A (Prosedür)',
        kalifikasyon='',
        not_='Bu dosya ilk sürümdür; IQ/OQ protokolleri ayrı hazırlanmalı '
             've yazılım güncellemeleriyle senkron tutulmalıdır.',
    ),
]

FIELD_ORDER = [
    'no', 'ad', 'madde', 'yazilim', 'tetik', 'permissive', 'etki', 'alarm',
    'gecikme', 'bypass', 'failsafe', 'kritik', 'durum', 'kalifikasyon',
    'not_',
]

wb = Workbook()
ws = wb.active
ws.title = 'Interlock Matrisi'

ws.append(HEADERS)
for c in range(1, len(HEADERS) + 1):
    cell = ws.cell(row=1, column=c)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(horizontal='center', vertical='center',
                                wrap_text=True)
    cell.border = BORDER
ws.freeze_panes = 'C2'
ws.row_dimensions[1].height = 32

for row in ROWS:
    values = [row[f] for f in FIELD_ORDER]
    ws.append(values)
    r = ws.max_row
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=r, column=c)
        cell.alignment = Alignment(horizontal='left', vertical='top',
                                    wrap_text=True)
        cell.border = BORDER
    ws.cell(row=r, column=1).alignment = Alignment(horizontal='center',
                                                     vertical='top')
    ws.cell(row=r, column=1).font = Font(bold=True)
    ws.cell(row=r, column=2).font = Font(bold=True)
    # Kritiklik (col 12) renklendirme
    k_cell = ws.cell(row=r, column=12)
    k_cell.fill = KRITIK_FILL.get(row['kritik'], PatternFill())
    k_cell.alignment = Alignment(horizontal='center', vertical='top')
    # Durum (col 13) renklendirme
    d_cell = ws.cell(row=r, column=13)
    d_cell.fill = DURUM_FILL.get(row['durum'], PatternFill())
    d_cell.alignment = Alignment(horizontal='center', vertical='top',
                                  wrap_text=True)

# Kalifikasyon sütununa açılır liste (IQ/OQ durumu manuel doldurulacak)
dv = DataValidation(
    type='list',
    formula1='"Beklemede,IQ Tamamlandı,OQ Tamamlandı,Doğrulandı,N/A"',
    allow_blank=True,
)
ws.add_data_validation(dv)
dv.add(f'N2:N{ws.max_row}')

widths = [5, 30, 34, 34, 30, 30, 32, 26, 16, 30, 34, 12, 16, 18, 40]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w

# ── Sayfa 2: GMP Madde → Interlock No çapraz referansı ──────────────
ws2 = wb.create_sheet('Madde Eşleme')
ws2.append(['#', 'GMP Metni (paragraf cümlesi)', 'İlişkili Interlock No'])
for c in range(1, 4):
    cell = ws2.cell(row=1, column=c)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(horizontal='center', vertical='center',
                                wrap_text=True)
    cell.border = BORDER

MADDE_ESLEME = [
    ('Grade A kritik alanın bütünlüğünü koruyacak, bariyer sistemine '
     'kontrolsüz erişimi önleyecek şekilde tasarlanmalı', '1, 2, 3'),
    ('Rutin operasyonlar, müdahaleler ve malzeme transferleri sırasında '
     'kontaminasyon riskini minimize edecek şekilde tasarlanmalı', '3, 4'),
    ('oRABS\'e erişim sağlayan kapılar ve transfer lock kapıları, '
     'karşılıklı kapıların aynı anda açılmasını önleyecek şekilde '
     'interlock edilmeli', '2'),
    ('...ve/veya gerekli çevresel koşulları bozabilecek şartlarda kapı '
     'açılmasını önleyecek şekilde interlock edilmeli', '3, 5, 7'),
    ('Interlock mantığı; operasyonel durum, hava akışı/havalandırma, '
     'kritik basınç, makine çalışma modu ve proses adımları dikkate '
     'alınarak oluşturulmalı', '5, 7'),
    ('Güvenli kapı açılmasına izin vermeyen durumda operatöre uygun '
     'görsel ve/veya sesli uyarı verilmeli', '3, 7, 8'),
    ('Bypass/override fonksiyonu rutin operasyon amacıyla kullanılmamalı; '
     'yalnızca yetkilendirilmiş personele açık, tanımlı, alarm/kayıt '
     'oluşturan ve risk değerlendirmesiyle yönetilen olmalı', '5, 10'),
    ('Elektrik kesintisi, yeniden başlatma veya kritik yardımcı sistem '
     'kaybı sonrası fail-safe duruma geçilmeli; koşullar sağlanmadan '
     'aseptik operasyona devam edilmemeli', '6, 9'),
    ('GMP/proses güvenliği açısından kritik interlocklar, permissive\'ler, '
     'alarmlar, zaman gecikmeleri ve override\'lar Interlock Matrisi\'nde '
     'tanımlanmalı ve kalifikasyonla doğrulanmalı', '11'),
]
for i, (metin, no) in enumerate(MADDE_ESLEME, start=1):
    ws2.append([i, metin, no])
    r = ws2.max_row
    for c in range(1, 4):
        cell = ws2.cell(row=r, column=c)
        cell.alignment = Alignment(horizontal='left', vertical='top',
                                    wrap_text=True)
        cell.border = BORDER
    ws2.cell(row=r, column=1).alignment = Alignment(horizontal='center',
                                                       vertical='top')
    ws2.cell(row=r, column=3).alignment = Alignment(horizontal='center',
                                                       vertical='top')

ws2.column_dimensions['A'].width = 5
ws2.column_dimensions['B'].width = 90
ws2.column_dimensions['C'].width = 20
ws2.freeze_panes = 'B2'

OUT = 'oRABS_Interlock_Matrisi.xlsx'
wb.save(OUT)
print(f'Yazıldı: {OUT}')
