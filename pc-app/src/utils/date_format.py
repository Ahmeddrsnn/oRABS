"""
Türkiye tarih/saat formatlama yardımcıları
Tüm kullanıcıya gösterilen tarihler DD.MM.YYYY HH:MM:SS formatında olmalıdır.
"""

from datetime import datetime

# ISO / DB → Türkiye formatına çeviren yardımcı parsers
_PARSE_FORMATS = (
    '%Y-%m-%dT%H:%M:%S.%f',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S.%f',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d',
)

TR_DATETIME_FMT = '%d.%m.%Y %H:%M:%S'
TR_DATE_FMT = '%d.%m.%Y'


def format_datetime_tr(value, fallback='N/A'):
    """
    Herhangi bir ISO/DB tarih string'ini Türkiye formatına çevirir.
    Örnekler:
        '2026-03-03T14:30:45.123' → '03.03.2026 14:30:45'
        '2026-03-03 14:30:45'     → '03.03.2026 14:30:45'
        '2026-03-03'              → '03.03.2026'
        datetime nesnesi          → '03.03.2026 14:30:45'
    """
    if value is None:
        return fallback

    # datetime objesi
    if isinstance(value, datetime):
        return value.strftime(TR_DATETIME_FMT)

    s = str(value).strip()
    if not s:
        return fallback

    for fmt in _PARSE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # Sadece tarih içeriyorsa saat ekleme
            if fmt == '%Y-%m-%d':
                return dt.strftime(TR_DATE_FMT)
            return dt.strftime(TR_DATETIME_FMT)
        except ValueError:
            continue

    # Hiçbir format uymadıysa orijinali döndür
    return s


def now_tr():
    """Şu anki zamanı Türkiye formatında döndürür."""
    return datetime.now().strftime(TR_DATETIME_FMT)
