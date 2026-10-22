---
description: GLT_v3 proje kuralları hatırlatması
---

# Proje Kuralları (.cursorrules Özeti)

## Zorunlu Kurallar
1. **Türkçe iletişim** — tüm açıklamalar, planlar, yorumlar Türkçe
2. **Plan önce, onay sonra** — kod değişikliği yapmadan ÖNCE plan aç, kullanıcı onayı AL
3. **`/*dogrulandı*/` bloklarına DOKUNMA** — bu bloklar kesin kod
4. **Logger kullan** — `Serial.print` YASAK, `LOG_INFO/WARN/ERROR` kullan
5. **Config.h/Config.cpp** — sabitler buradan yönetilmeli
6. **Müzik bildirimi** — build/upload komutlarından önce `play_success_music.py start`, sonra `finish`
7. **safe_upload.bat** — upload için her zaman bu kullanılmalı
8. **Derleme kontrolü** — her değişiklik sonrası `pio run`

## Dikkat Edilecekler
- `/*dogrulandı*/` yorumlu satırları kesinlikle değiştirme
- Mevcut lojik bozulmadan sadece odaklanılan kısmı güncelle
- Hata durumunda logları incele, rastgele deneme yapma
