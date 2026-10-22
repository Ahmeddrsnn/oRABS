---
description: GLT_v3 projesinde derleme ve yükleme işlemi
---

# Derleme ve Yükleme İş Akışı

// turbo-all

## 1. Müzik Bildirimi (Başlangıç)
```bash
python play_success_music.py start
```

## 2. Güvenli Yükleme (safe_upload.bat)
```bash
cmd /c safe_upload.bat
```

## 3. Müzik Bildirimi (Bitiş)
```bash
python play_success_music.py finish
```

## Notlar
- Sadece derleme (upload'sız): `pio run` kullan, `safe_upload.bat` yerine
- Varsayılan port: COM23
- Serial Monitor: `python serial_debug.py` (standart PlatformIO monitörü DEĞİL)
- Her build/upload öncesi müzik START, sonrası müzik FINISH çalıştır
