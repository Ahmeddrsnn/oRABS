# Ultra GITS PC Yazılımı Kullanım Kılavuzu

Metin sürümü  
Yazılım sürümü: 1.0.0  
Doküman revizyonu: 30.07.2026  
Üretici: LCC Technology Ltd. Şti.

Bu kılavuz, Ultra GITS PC yazılımının güncel kaynak koduna göre hazırlanmıştır. Yazılım; ORABS tesis/kapı yönetimi, eldiven sızdırmazlık testi (GLT), LAF izleme, Weidmüller IO, kullanıcı yönetimi, elektronik imza, raporlama ve denetim izi işlevlerini aynı uygulamada birleştirir.

# İçindekiler

1. Kılavuz Hakkında
2. Sisteme Başlangıç ve Güvenli Giriş
3. Kullanıcı Rolleri ve Yetkiler
4. Ana Ekran ve Gezinme
5. ORABS Genel Bakış
6. ORABS Batch Yönetimi
7. LAF İzleme
8. Weidmüller IO İzleme ve Yönetimi
9. GLT Cihazlar ve Eldiven Testi
10. GLT Yerleşim Planı
11. GLT Batch Yönetimi
12. Test Reçeteleri
13. Test Raporları ve Elektronik İmza
14. Audit Trail
15. Kullanıcı Yönetimi
16. Sistem, GLT ve ORABS Ayarları
17. Veri Saklama ve Rapor Arşivi
18. Günlük Operatör İş Akışı
19. Sorun Giderme
20. Güvenli Kapatma

# 1. Kılavuz Hakkında

## 1.1. Amaç ve Kapsam

Bu kılavuzun amacı, Ultra GITS yazılımını kullanan operatör, supervisor ve sistem yöneticilerine günlük işlemleri güvenli ve izlenebilir biçimde gerçekleştirebilmeleri için adım adım açıklama sağlamaktır.

Kılavuz aşağıdaki işlevleri kapsar:

- Kullanıcı girişi, parola değiştirme ve oturum yönetimi
- ORABS 3B modelinin izlenmesi ve eşleme işlemleri
- Kapı grupları, kapı konfigürasyonları ve ORABS batch yönetimi
- LAF sensörlerinin ve alarmlarının izlenmesi
- Weidmüller Modbus TCP IO modüllerinin görüntülenmesi
- GLT cihazlarının PC'ye bağlanması ve senkronizasyonu
- RFID etiketlerinin port ve reçete ile eşleştirilmesi
- Eldivenin bağlanması, testin başlatılması, izlenmesi ve bitirilmesi
- GLT batch şablonları ve toplu test işlemleri
- Reçete oluşturma ve düzenleme
- PDF raporu, elektronik imza ve Audit Trail işlemleri
- Kullanıcı, depolama, güvenlik, rapor ve donanım ayarları

Bu kılavuz bir doğrulama protokolü, bakım talimatı veya tesis SOP'sinin yerine geçmez. Tesisin onaylı prosedürleri ile bu metin arasında fark bulunursa tesis prosedürü ve yetkili kalite birimi kararı uygulanmalıdır.

## 1.2. Yazılımın Ana Bileşenleri

Ultra GITS dört ana çalışma alanından oluşur:

- ORABS: 3B tesis görünümü, kapı ve port durumları, kapı batch'leri, LAF ve IO izleme
- GLT: eldiven test cihazları, portlar, reçeteler, GLT batch'leri ve test raporları
- Audit Trail: kullanıcı, GLT, ORABS, LAF ve sistem olaylarının merkezi denetim izi
- Yönetim: kullanıcılar, dil, depolama, parola, rapor, GLT ve ORABS ayarları

## 1.3. Önemli Güvenlik Uyarıları

DİKKAT: Conta indirme (Dismount) işleminden önce cihaz fiziksel olarak tutulmalıdır. Yazılım, düşme riskine karşı dört haneli doğrulama kodu ister; bu kod güvenli tutuşun yerine geçmez.

DİKKAT: 3B görünümde sarı kapı fiziksel açık sensörünü, turuncu kapı aktif ışık bariyerini, kırmızı kapı kilitli durumu gösterir. Fiziksel alan kontrol edilmeden batch devam ettirilmemelidir.

DİKKAT: Acil stop aktif olduğunda yazılım sesli uyarı üretir ve çalışan batch'i otomatik duraklatabilir. Acil stopun fiziksel sebebi giderilmeden yazılımdan devam komutu verilmemelidir.

DİKKAT: IO ekranındaki DO ve AO kontrolleri fiziksel çıkışlara komut gönderebilir. Bu işlemler yalnızca yetkili bakım veya sistem yöneticisi tarafından, saha güvenliği sağlandıktan sonra yapılmalıdır.

NOT: Kritik değişiklikler, batch işlemleri, kullanıcı işlemleri, eşlemeler, parola olayları ve rapor imzaları Audit Trail'e kaydedilir.

## 1.4. Terimler

ORABS: Açık veya kapalı erişim bariyer sisteminin kapı, port, sensör ve tesis görünümünü yöneten yazılım bölümü.

GLT: Glove Leak Test; eldiven sızdırmazlık testi bölümü.

Batch: Belirli bir üretim veya kontrol oturumunda birlikte yönetilen kapı ya da port grubu.

Konfig: ORABS batch'i sırasında hangi kapı gruplarının açık veya kilitli olacağını ve hangi GLT portlarının batch'e dahil edileceğini belirleyen şablon.

Reçete: Eldiven test basıncı, süreleri ve kabul limitlerinden oluşan parametre seti.

RFID: Eldiven portunu tanımlayan benzersiz elektronik etiket.

LAF: Laminar Air Flow; temiz alan hava akışını veya bağlı çevresel sensörleri izleyen bölüm.

DI/DO/AI/AO: Sırasıyla dijital giriş, dijital çıkış, analog giriş ve analog çıkış.

Audit Trail: Kullanıcı ve sistem işlemlerinin zaman damgalı, kullanıcı bağlantılı denetim izi.

# 2. Sisteme Başlangıç ve Güvenli Giriş

## 2.1. Başlatma Öncesi Kontrol

Yazılımı başlatmadan önce aşağıdaki koşulları kontrol edin:

- PC Windows 10 veya Windows 11 üzerinde çalışıyor olmalıdır.
- GLT ana haberleşme cihazı kullanılacaksa USB bağlantısı ve uygun COM portu hazır olmalıdır.
- ORABS IO kullanılacaksa PC ile Weidmüller modülleri aynı erişilebilir ağda olmalıdır.
- LAF kullanılacaksa USB/seri bağlantı ve tanımlı COM portu hazır olmalıdır.
- Rapor ve veritabanı depolama klasörü erişilebilir olmalıdır.
- Tesisin güncel 3B GLB/GLTF modeli ayarlarda seçilmiş olmalıdır.

## 2.2. Yazılımı Başlatma

Kurulu sistemde GloveTestSystem.exe veya kurulum sırasında oluşturulan Ultra GITS kısayolunu çalıştırın. Geliştirme ortamında uygulama src/main.py üzerinden başlatılabilir; günlük kullanıcıların paketlenmiş uygulamayı kullanması önerilir.

Başlatma sırasında veritabanı, depolama yolları, cihaz haberleşmesi ve arka plan izleme servisleri hazırlanır. Giriş ekranı görüntülenmeden önce uygulamanın açılması birkaç saniye sürebilir.

## 2.3. Giriş Ekranı

Giriş ekranında aşağıdaki alanlar bulunur:

- Username: Sistem yöneticisi tarafından tanımlanan kullanıcı adı
- Password: Kullanıcı parolası
- Login: Bilgileri doğrular ve oturumu açar
- Exit: Uygulamayı kapatır

Giriş yapmak için:

1. Kullanıcı adınızı Username alanına yazın.
2. Parolanızı Password alanına yazın.
3. Login düğmesine basın veya parola alanında Enter tuşuna basın.
4. Başarılı giriş mesajında tam adınızı ve rolünüzü kontrol edin.
5. Ana ekran açıldığında rolünüze uygun sekmeler görüntülenir.

Başarılı ve başarısız giriş denemeleri Audit Trail'e kaydedilir.

## 2.4. İlk Giriş ve Zorunlu Parola Değişikliği

Yeni kullanıcılar ilk girişte geçici parolalarını değiştirmeden uygulamayı kullanamaz. Parola süresi, sistem ayarındaki 3, 6, 9 veya 12 aylık periyoda ulaştığında aynı pencere yeniden görüntülenir.

Yeni parola şu koşulları karşılamalıdır:

- En az 8 karakter
- En az bir büyük harf
- En az bir küçük harf
- En az bir rakam
- En az bir özel karakter
- Eski paroladan farklı olma

Yeni Şifre ve Tekrar alanlarına aynı parolayı yazın, ardından Kaydet ve Giriş Yap düğmesine basın.

## 2.5. Başarısız Giriş ve Hesabın Pasif Olması

Admin dışındaki bir kullanıcı üç kez art arda hatalı parola girerse hesabı güvenlik amacıyla pasif duruma alınır. Ekranda kalan deneme hakkı gösterilir.

Pasif hesabın yeniden açılması için Admin kullanıcısı:

1. Kullanıcı sekmesini açar.
2. İlgili kullanıcıyı seçer.
3. Aktif/Pasif düğmesine basar.
4. Hesabı Aktif duruma getirir.

Hesap yeniden etkinleştirildiğinde başarısız giriş sayacı sıfırlanır. Ana admin hesabı bu otomatik pasifleştirme kuralından muaftır; yine de tüm hatalı denemeler kaydedilir.

## 2.6. Üst Bilgi Alanı

Ana pencerenin sağ üst bölümünde aşağıdaki kontroller bulunur:

- Oturum bilgisi: Giriş yapan kullanıcının tam adı ve rolü
- PIN Görüntüle: GLT cihaz ekranında kullanılacak dört haneli kullanıcı PIN'ini gösterir veya yeniler
- Şifre Değiştir: Kullanıcının kendi parolasını, mevcut parolayı doğrulayarak değiştirmesini sağlar
- Çıkış Yap: Oturumu kilitli moda geçirir
- Pencere düğmeleri: Admin ve Supervisor için küçült, pencere/tam ekran ve kapat kontrolleri

PIN yalnızca yetkili kullanıcı tarafından görülmeli, paylaşılmamalı ve ekranda açık bırakılmamalıdır.

## 2.7. Oturum Zaman Aşımı ve Kilitli Mod

Ayarlanan süre boyunca kullanıcı etkileşimi olmazsa oturum otomatik olarak kapanabilir. Manuel Çıkış Yap işleminde de uygulama kapanmaz; ORABS canlı verileri çalışmaya devam eder ancak kullanıcı eylemleri kilitlenir.

Yeniden giriş yapmak için sağ üstteki Giriş Yap düğmesine basın ve kimlik bilgilerinizi girin.

# 3. Kullanıcı Rolleri ve Yetkiler

## 3.1. Admin

Admin en yüksek yetki seviyesidir. Başlıca yetkileri:

- ORABS, GLT, Audit Trail, Kullanıcı ve Ayarlar sekmelerine erişim
- Kullanıcı oluşturma, düzenleme, parola sıfırlama ve hesap durumunu değiştirme
- ORABS 3B model, LAF, Weidmüller, bariyer ve depolama ayarlarını değiştirme
- IO modüllerini ve IO noktalarını tanımlama/eşleme
- Sekme görünürlüğünü değiştirme
- GLT ve ORABS yapılandırmalarını yönetme
- Reçete ve batch şablonu oluşturma/düzenleme

Admin hesabı yalnızca sistem yönetimi için kullanılmalı; normal üretim işlemlerinde kişiye özel kullanıcı hesabı tercih edilmelidir.

## 3.2. Supervisor

Supervisor, üretim yapılandırması ve gözden geçirme işlemlerini yapabilen ara yetki seviyesidir. Başlıca yetkileri:

- ORABS, GLT, Audit Trail ve genel Ayarlar sekmelerini görüntüleme
- ORABS kapı adlarını ve kapı gruplarını yönetme
- ORABS batch konfigürasyonlarını oluşturma/düzenleme
- GLT reçetelerini ve GLT batch şablonlarını yönetme
- Cihaz adını düzenleme
- Test, batch ve rapor işlemlerini yürütme

Supervisor kullanıcı yönetimi, depolama, donanım IO ve yöneticiye özel güvenlik ayarlarını değiştiremez.

## 3.3. Operator

Operator günlük üretim akışı için tasarlanmıştır. Varsayılan olarak ORABS Genel Bakış ekranını tam ekran görür.

Başlıca yetkileri:

- Aktif sistemi ve alarmları izleme
- Önceden hazırlanmış ORABS konfigürasyonu ile batch başlatma
- Batch'i duraklatma, devam ettirme ve bitirme
- Yetkili akış içinde geçici kapı grubu kilidi açma/kilitleme
- Bağlı GLT cihazlarının durumunu izleme ve kendisine açık test işlemlerini yürütme

Operator yeni kullanıcı, reçete, IO modülü veya batch konfigürasyonu oluşturamaz.

## 3.4. Eski Viewer Kayıtları

Önceki veritabanlarından Viewer rolü kalmış olabilir. Bu rol yetki hiyerarşisinde salt okunur seviyededir. Güncel kullanıcı oluşturma ekranında standart roller Operator, Supervisor ve Admin'dir.

## 3.5. Sekme Görünürlüğü ve Yetki Farkı

Admin, Ayarlar içindeki Sekme Görünürlüğü bölümünden bazı sekmeleri gizleyebilir. Bir sekmenin gizlenmesi yetki vermek veya yetki kaldırmak anlamına gelmez. Rol kontrolü her zaman önceliklidir; kullanıcı yalnızca rolünün izin verdiği işlemleri yapabilir.

# 4. Ana Ekran ve Gezinme

## 4.1. Ana Sekmeler

Uygulamada rol ve sistem ayarına bağlı olarak şu ana sekmeler bulunur:

- ORABS
- GLT
- Kullanıcı
- Audit Trail
- Ayarlar

Girişten sonra başlangıç ekranı ORABS Genel Bakış'tır.

## 4.2. ORABS Alt Sekmeleri

Rol ve ayara bağlı olarak ORABS içinde şu sekmeler bulunur:

- Genel Bakış
- Batch
- LAF
- IO
- Ayarlar

Operator için yalnız Genel Bakış gösterilir. IO ve ORABS Ayarlar yalnız Admin'e görünür.

## 4.3. GLT Alt Sekmeleri

GLT içinde şu sekmeler bulunur:

- Gösterge Paneli / Cihazlar
- Yerleşim Planı / Eldiven Portu
- Batch
- Reçete
- Rapor
- GLT Ayarları

GLT Ayarları yalnız Admin'e görünür. Reçete ve batch şablonu değişiklikleri Admin veya Supervisor yetkisi gerektirir.

## 4.4. İki Farklı Batch Kavramı

Yazılımda iki farklı ancak birbirine bağlanabilen batch iş akışı vardır:

- ORABS Batch: Kapı gruplarının açık/kilitli durumunu ve seçili ORABS/GLT portlarını yönetir.
- GLT Batch: RFID ile tanımlı eldiven portlarının test sonuçlarını toplar, PASS/FAIL/PENDING durumlarını izler ve PDF özet raporu üretir.

İşletme prosedürünüz hangisini kullanıyorsa batch'i doğru sekmeden başlatın. Entegre konfigürasyonda ORABS batch'i, seçili GLT portlarının test ilerlemesini de Genel Bakış ekranında gösterebilir.

# 5. ORABS Genel Bakış

## 5.1. Ekranın Bölümleri

ORABS Genel Bakış ekranı aşağıdaki alanlardan oluşur:

- Aktif alarm şeridi
- 3B Cihaz Görünümü
- Eşleme ve görünüm düğmeleri
- Aktif Batch kartı ve hızlı batch kontrolleri
- Rapor düğmeleri
- Son Olaylar
- LAF Ünitesi özeti
- Bağlı GLT Cihazları

## 5.2. 3B Cihaz Görünümü

3B model, tanımlı kapıları, eldiven portlarını ve LAF sensörlerini tesis yerleşimi üzerinde gösterir. Model dosyası, birimi ve gösterilecek yönler ORABS Ayarları'ndan belirlenir.

3B görünümde kapı renkleri:

- Yeşil: Batch konfigürasyonuna göre açık
- Kırmızı: Batch konfigürasyonuna göre kilitli
- Sarı: DI kapı sensörü fiziksel açık durumu bildiriyor
- Turuncu: Kapıya bağlı ışık bariyeri aktif
- Gri veya modelin doğal rengi: Nötr, batch dışında veya IO'ya bağlı değil

3B görünümde port renkleri:

- Yeşil: GLT cihazı/RFID porta bağlı
- Gri: Boş port
- Mavi: Kablosuz bariyer sensörü hareket algıladı
- Mor: Aktif batch üyesi, test bekliyor
- Camgöbeği: Test PASS
- Pembe: Test FAIL

Renkler sahadaki fiziksel kontrolün yerine geçmez. Sensör, haberleşme veya eşleme hatasında görüntü güncel olmayabilir.

## 5.3. Alarm Şeridi

Acil stop, kritik interlock, LAF alarmı veya benzeri kritik olay oluştuğunda ekranın üstünde kırmızı, yanıp sönen bir alarm şeridi görüntülenir.

Alarmı onaylamak için Tamam düğmesine basın. Bu işlem:

- Alarmın görüldüğünü kullanıcı oturumu için onaylar
- ALARM_ACKED kaydını Audit Trail'e ekler
- Fiziksel alarm sebebini ortadan kaldırmaz

Aynı alarm tekrar oluşursa şerit yeniden görünür.

## 5.4. RFID Eşleme Modu

RFID Eşleme Modu, GLT'de kayıtlı bir RFID etiketini 3B modeldeki eldiven portuna bağlamak için kullanılır. Admin veya Supervisor:

1. RFID Eşleme Modu düğmesini etkinleştirir.
2. Gerekirse Döndür düğmesini açarak modeli uygun açıya getirir.
3. 3B modelde ilgili porta tıklar.
4. Açılan pencerede port adını yazar.
5. GLT'de kayıtlı RFID listesinden doğru etiketi seçer.
6. Port ad etiketinin 3B görünümde gösterilip gösterilmeyeceğini belirler.
7. Eşle düğmesiyle kaydeder.

Yanlış eşlemeyi kaldırmak için aynı portu açıp Eşlemeyi Temizle seçeneğini kullanın.

## 5.5. Kapı Eşleme Modu

Kapı Eşleme Modu, 3B modeldeki kapılara ad ve grup atamak için kullanılır:

1. Kapı Eşleme Modu'nu etkinleştirin.
2. 3B modelde kapıya tıklayın.
3. Kapı adını yazın veya güncelleyin.
4. Mevcut bir kapı grubu seçin ya da artı düğmesiyle yeni grup oluşturun.
5. 3B ad etiketinin görünürlüğünü belirleyin.
6. Kaydet düğmesine basın.

Kapı grupları, ORABS batch konfigürasyonunda tek bir mantıksal birim olarak kullanılır. Bir gruba yanlış kapı eklemek fiziksel kilit davranışını etkileyebilir.

## 5.6. Bariyer Eşleme Modu

Kablosuz bariyer sensörünü bir porta eşlemek için:

1. Bariyer Eşleme Modu'nu açın.
2. 3B modelde eşlenecek porta tıklayın.
3. İlgili fiziksel sensörün önünden elinizi geçirin.
4. Yazılımın algıladığı sensör ve port eşlemesini onaylayın.

Sensör otomatik algılanamazsa yazılım kayıtlı sensör listesinden manuel seçim sunabilir. Eşleme, port hareket olaylarının 3B görünümde mavi olarak gösterilmesini sağlar.

## 5.7. Döndür, Yerleşim Modu ve Ad Etiketleri

Döndür: Eşleme sırasında modeli serbestçe döndürür. Döndür kapalıyken tıklama, kapı veya port seçimi olarak işlenir.

Yerleşim Modu: LAF sensör göstergelerini 3B model üzerinde sürükleyerek yerleştirir. Bu işlem Admin veya Supervisor yetkisi gerektirir.

Ad Etiketleri: Kapı ve port adlarını topluca gösterir veya gizler. Tekil görünürlük, ilgili kapı/port düzenleme penceresinden ayrıca seçilebilir.

## 5.8. Aktif Batch Kartı

Aktif batch yokken kartta Batch adı, konfigürasyon seçimi ve Başlat düğmesi görüntülenir.

Batch başlatmak için:

1. Batch adını yazın.
2. Önceden hazırlanmış konfigürasyonu seçin.
3. Başlat düğmesine basın.
4. Ekrandaki batch adı, konfigürasyon, kapı sayıları ve port sayaçlarını kontrol edin.

Aktif batch sırasında kart; çalışan/duraklatılmış durumunu, açık/kilitli kapı sayısını ve varsa GLT portlarının geçti, başarısız ve bekleyen sayılarını gösterir.

## 5.9. Batch'i Duraklatma ve Geçici Kilit İşlemleri

Batch çalışırken Duraklat düğmesine basıldığında kilit kontrolü duraklatılmış batch durumuna geçer.

Duraklatılmış batch'te bir kapı grubunun kilidini geçici açmak için:

1. Kilit Aç düğmesine basın.
2. Kapı grubunu seçin.
3. Zorunlu açıklamayı yazın.
4. İşlemi onaylayın.
5. 3B görünüm ve fiziksel kapı durumunu kontrol edin.

Grubu yeniden kilitlemek için Kilitle düğmesini kullanın ve zorunlu açıklama girin.

Devam düğmesine basıldığında geçici kapı durumu geçersiz kılmaları temizlenir ve konfigürasyonun asıl durumları yeniden uygulanır.

## 5.10. Batch'i Bitirme

Bitir düğmesine basıldığında sistem aktif ORABS batch'ini sonlandırır. Entegre bir GLT batch'i varsa FAIL açıklamaları, test edilmemiş portlar, şifre onayı ve PDF raporu gibi GLT bitirme adımları da çalıştırılabilir.

Batch bitmeden önce:

- Fiziksel kapıların güvenli durumda olduğunu doğrulayın.
- Bekleyen veya FAIL portları inceleyin.
- Gerekli açıklamaları hazırlayın.
- Raporların yazılacağı klasörün erişilebilir olduğundan emin olun.

## 5.11. Raporlar ve Bilgi Kartları

Raporları Görüntüle düğmesi, GLT Test Raporları, Batch Raporları ve Audit Trail Raporları sekmelerini içeren arşiv penceresini açar. Arama ve tarih aralığı filtreleri kullanılabilir; satıra çift tıklayarak PDF uygulama içinde açılır.

Rapor düğmesi, aktif veya son batch için uygun rapor üretme akışını başlatır.

Son Olaylar kartı yakın zamanda oluşan önemli işlemleri gösterir.

LAF Ünitesi kartı, Admin tarafından ana ekranda gösterilmek üzere seçilen sensörlerin değerlerini ve aktif alarmları özetler.

Bağlı GLT Cihazları kartı, haberleşmesi doğrulanmış cihazları gösterir. Bir karta tıklamak GLT Gösterge Paneli'ne geçiş yapar.

# 6. ORABS Batch Yönetimi

## 6.1. Batch Sekmesinin Amacı

ORABS Batch sekmesi, üretim sırasında hangi kapı gruplarının açık veya kilitli olacağını önceden tanımlar. Konfigürasyon; kapı grubu durumları ile batch'e dahil edilecek RFID eşleştirilmiş portları saklar.

Admin ve Supervisor konfigürasyon oluşturabilir. Giriş yapmış kullanıcılar hazırlanmış konfigürasyonla batch başlatabilir.

## 6.2. Konfigürasyon Ön Koşulları

Yeni konfigürasyon oluşturmadan önce:

- 3B model yüklenmiş olmalıdır.
- Kapılar Kapı Eşleme Modu ile adlandırılmış ve gruplara atanmış olmalıdır.
- Fiziksel kilit çıkışları kullanılacaksa ilgili kapı veya kapı grubu bir DO noktasına bağlanmış olmalıdır.
- Batch'e GLT portu eklenecekse portun RFID eşlemesi yapılmış olmalıdır.

DO çıkışına bağlı olmayan kapı grupları konfigürasyon seçiminde görünmeyebilir.

## 6.3. Yeni Konfigürasyon Oluşturma

1. ORABS > Batch sekmesini açın.
2. Yeni Konfig düğmesine basın.
3. Konfig Adı ve Açıklama alanlarını doldurun.
4. Her kapı grubu için Açık veya Kilitli durumunu seçin.
5. Gerekirse Hepsini Aç, Hepsini Kilitle veya Tersine Çevir düğmelerini kullanın.
6. Port Seçimi bölümünden batch'e dahil edilecek RFID eşleştirilmiş portları seçin.
7. Kaydet düğmesine basın.

Konfigürasyon tablosunda Ad, Açık, Kilitli ve Açıklama bilgileri gösterilir.

## 6.4. Konfigürasyon Düzenleme ve Silme

Düzenle düğmesi mevcut kapı durumlarını, açıklamayı ve port listesini değiştirir.

Sil düğmesi konfigürasyonu izlenebilirlik amacıyla soft delete yöntemiyle pasife alır. Geçmiş batch kayıtları korunur. Aktif batch tarafından kullanılan konfigürasyon değiştirilemeyebilir.

## 6.5. Batch Başlatma

1. Yeni Batch alanına benzersiz ve anlamlı bir ad yazın.
2. Konfigürasyon listesinden doğru kaydı seçin.
3. Başlat düğmesine basın.
4. Aktif Batch kartında başlatan kullanıcı, tarih/saat, konfigürasyon ve durumu doğrulayın.
5. 3B görünümde kapı renklerini ve fiziksel sahayı karşılaştırın.

Aynı anda yalnız bir ORABS batch aktif olabilir.

## 6.6. Duraklatma, Devam ve Bitirme

Duraklat: Çalışan batch'i paused durumuna geçirir.

Devam Et: Duraklatılmış batch'i yeniden çalıştırır ve geçici kapı durumu değişikliklerini temizleyerek asıl konfigürasyonu uygular.

Bitir: Aktif batch'i finished durumuna geçirir ve olayı Audit Trail'e kaydeder.

## 6.7. Interlock Davranışı

Işık bariyeri otomatik duraklatma ayarı etkinse bariyer ihlali çalışan batch'i otomatik duraklatır. Acil stop da batch'i duraklatabilir.

Interlock sonrası:

1. Alarm sebebini fiziksel alanda doğrulayın.
2. Alanı güvenli hale getirin.
3. Alarm şeridini yalnızca durumu gördüğünüzü belirtmek için onaylayın.
4. Gerekirse sorumlu Supervisor veya Admin'e haber verin.
5. Devam etmeden önce kapı, bariyer ve IO göstergelerini yeniden kontrol edin.

# 7. LAF İzleme

## 7.1. LAF Sekmesi

LAF sekmesi, tanımlı sensörlerin canlı değerlerini kartlar halinde gösterir. Üst alanda bağlantı durumu, Yenile ve Ana Ekran Sensörleri düğmeleri bulunur.

Her sensör kartında:

- Sensör etiketi
- Güncel değer
- Birim
- Son okuma saati
- Alarm durumu

## 7.2. Cihaz Alarmları

Cihaz Alarmları listesinde son alarm kayıtları görüntülenir. Uyarı işareti aktif alarmı, onay işareti sona ermiş alarmı gösterebilir.

LAF alarmı ayrıca ORABS Genel Bakış'taki kırmızı alarm şeridinde gösterilebilir.

## 7.3. Snapshot

Yazılım sensör değerlerini ayarlanan periyotta veritabanına otomatik kaydeder. Şimdi Snapshot Al düğmesi mevcut değerleri anında kaydeder.

Okuma alınmamışsa manuel snapshot oluşturulamaz.

## 7.4. Tarih Aralığı Raporu

1. Tarih Aralığı Raporu (CSV) düğmesine basın.
2. Başlangıç ve Bitiş tarih/saatini seçin.
3. Kaydetme konumunu belirleyin.
4. Oluşturulan CSV dosyasını doğrulayın.

CSV dosyası zaman damgası, sensör kimliği, etiket, değer ve birim alanlarını içerir.

## 7.5. Ana Ekran Sensörlerini Seçme

Ana Ekran Sensörleri düğmesi, ORABS Genel Bakış LAF kartında hangi sensörlerin gösterileceğini belirler. İlgili satırların Ana Ekran kutusunu işaretleyin ve kaydedin.

# 8. Weidmüller IO İzleme ve Yönetimi

## 8.1. IO Sekmesi

IO sekmesi yalnız Admin'e görünür. Aktif Weidmüller modülleri ve canlı IO noktaları dört grupta gösterilir:

- Dijital Girişler (DI)
- Dijital Çıkışlar (DO)
- Analog Girişler (AI)
- Analog Çıkışlar (AO)

Modül başlığında ad, IP adresi, port, unit ID, bağlantı durumu ve coupler bilgisi yer alır.

## 8.2. DI ve AI İzleme

DI noktaları kapı sensörü, bariyer veya acil stop gibi fiziksel girişlerin durumunu gösterir.

AI noktaları ham değer, yüzde ve varsa ölçeklenmiş mühendislik değerini gösterir. Düşük/yüksek alarm eşikleri tanımlanmışsa alarm olayları Audit Trail'e yazılabilir.

## 8.3. DO ve AO Komutları

DO noktalarında açık/kapalı komutu, AO noktalarında yüzde değeri yazılabilir.

DİKKAT: Manuel çıkış yazmadan önce:

- Noktanın bağlı olduğu fiziksel hedefi kontrol edin.
- Aktif batch ve interlock durumunu kontrol edin.
- Sahada insan veya ekipman riski olmadığını doğrulayın.
- Değişikliğin bakım prosedürüne uygun olduğundan emin olun.

## 8.4. Eşlenmemiş IO Uyarısı

IO noktası hiçbir kapı, kapı grubu, port, LAF sensörü, bariyer veya acil stop hedefiyle eşlenmemişse Eşlenmemiş IO uyarısı görünür. Eşleme Ayarlar > ORABS > IO Modüllerini Düzenle > IO Noktalarını Düzenle yolundan yapılır.

# 9. GLT Cihazlar ve Eldiven Testi

## 9.1. GLT Gösterge Paneli

GLT Gösterge Paneli; PC ile ESP-NOW ana cihazı arasındaki COM bağlantısını, keşfedilen eldiven test cihazlarını, RFID durumlarını, komutları ve sistem loglarını gösterir.

Üst bağlantı alanında:

- Port seçimi
- Bağlan/Kes düğmesi
- Bağlantı göstergesi
- Otomatik Bağlan seçeneği

## 9.2. COM Bağlantısı

Manuel bağlantı için:

1. USB ana cihazın PC'ye bağlı olduğunu doğrulayın.
2. Port listesinden doğru COM portunu seçin.
3. Bağlan düğmesine basın.
4. Düğmenin Kes olarak değişmesini ve Bağlı göstergesini kontrol edin.
5. Cihaz kartlarının oluşmasını bekleyin.

Otomatik Bağlan işaretliyse uygulama sonraki açılışta kaydedilmiş portu kullanmayı veya uygun portu bulmayı dener.

Bağlantıyı kesmek için Kes düğmesine basın. Bağlantı kesildiğinde cihaz kartları çevrimdışı duruma geçer.

## 9.3. Cihaz Kartı

Her bağlı GLT cihazı ayrı kartla gösterilir. Kartta:

- Cihaz adı
- Kısa cihaz/MAC kimliği
- Wi-Fi/bağlantı göstergesi
- Manuel Senkronizasyon düğmesi
- Cihaz Ayarları düğmesi
- Conta durumunu gösteren oval
- RFID/port durumu
- Port Kaydet düğmesi
- Mount, Dismount, Testi Başlat ve İptal düğmeleri
- Bağlantı ve batarya bilgisi

Conta durum renkleri:

- Turuncu: Şişiriliyor
- Yeşil: Conta aktif
- Gri: Pasif

RFID tanımlı değilse test kontrol düğmeleri devre dışı kalır.

## 9.4. Yeni RFID ve Port Kaydı

Cihaz yeni bir RFID okuduğunda kartta Yeni RF ID ve Port Kaydet görünür.

1. Port Kaydet düğmesine basın.
2. Port Numarası alanına 12 gibi tek sayı veya 3/5 gibi çift taraflı port numarası yazın.
3. Salt okunur RFID değerini doğrulayın.
4. Aktif reçetelerden doğru reçeteyi seçin.
5. OK düğmesine basın.
6. Kartın tanımlı portu ve onay işaretini gösterdiğini doğrulayın.

Aynı port numarası başka RFID için kullanılıyorsa kayıt engellenir. Önce yanlış/eski port kaydı düzeltilmelidir.

## 9.5. Manuel Senkronizasyon

Karttaki Senkronizasyon düğmesi, PC'deki kullanıcı PIN ve RFID/reçete verileri ile cihaz verisini karşılaştırır. Eksik veya farklı kayıtlar cihaza gönderilir; cihazda olup PC'de bulunmayan eski kayıtlar temizlenebilir.

Senkronizasyon sırasında:

- Cihazı kapatmayın.
- USB/COM bağlantısını kesmeyin.
- Log alanındaki tamamlanma veya hata mesajını bekleyin.

## 9.6. Cihaz Ayarları ve Kalibrasyon

Cihaz Ayarları düğmesi:

- Cihaz kimliğini gösterir
- Admin veya Supervisor için cihaz adını değiştirir
- Canlı basınç değerini gösterir
- Basınç çarpanını yüzde olarak ayarlar
- Basıncı Sıfırla komutunu gönderir

Kaydet düğmesi kalibrasyon verisi cihazdan alınana kadar devre dışı olabilir. Kalibrasyon yalnızca geçerli referans ölçüm ve onaylı kalibrasyon prosedürü ile yapılmalıdır.

## 9.7. Mount

Mount düğmesi contayı şişirerek eldiven test cihazını porta sabitler.

Mount öncesi:

- Doğru RFID ve portun görüntülendiğini doğrulayın.
- Reçetenin doğru porta atandığını doğrulayın.
- Cihaz ve eldiven portunun hizalı olduğundan emin olun.
- Batarya seviyesini kontrol edin.

## 9.8. Testi Başlatma

1. Conta aktif olduktan sonra Testi Başlat düğmesine basın.
2. Canlı izleme penceresini açmak için cihaz kartına tıklayın.
3. RFID, port ve reçete bilgisini doğrulayın.
4. Şişirme, stabilizasyon ve ölçüm aşamalarını izleyin.
5. Basınç eğrisinin hedef ve limit çizgileriyle davranışını takip edin.
6. Test tamamlandığında PASS veya FAIL sonucunu kontrol edin.

Test akışındaki genel aşamalar:

- Montaj
- Şişirme
- Stabilizasyon
- Ölçüm
- Tamamlandı

## 9.9. Canlı Test Penceresi

Canlı test penceresinde:

- Zaman-basınç grafiği
- Hedef basınç çizgisi
- Kabul/başarısızlık limit çizgisi
- Aktif RFID, port ve reçete
- Reçete parametre özeti
- Aşama
- Geçen süre
- Batarya
- Anlık eldiven basıncı
- Test sonucu

PASS yeşil, FAIL kırmızı olarak gösterilir. Test sonunda grafik son durumda sabitlenir.

## 9.10. İptal / Havasını Al

İptal düğmesi devam eden testi durdurur veya cihazın havasını boşaltır. İptal edilen test sonucu ABANDONED veya tamamlanmamış olarak raporlanabilir.

İptal sebebi tesis prosedürüne göre kayda geçirilmelidir.

## 9.11. Dismount

Dismount düğmesi contayı indirir. Yazılım, kritik güvenlik penceresinde rastgele dört haneli bir kod gösterir.

1. Cihazı iki elle veya onaylı destekle güvenli biçimde tutun.
2. Ekrandaki kodu giriş alanına yazın.
3. Onayla ve İndir düğmesine basın.
4. Conta tamamen indikten sonra cihazı kontrollü biçimde ayırın.

Kodun doğru girilmesi fiziksel güvenliğin sağlandığı anlamına gelmez.

# 10. GLT Yerleşim Planı

## 10.1. Ekranın Amacı

Yerleşim Planı, kayıtlı GLT portlarını liste ve harita üzerinde yönetir. Sol panelde port, RFID ve reçete bilgileri; sağ panelde tesis resmi ve sürüklenebilir port işaretleri bulunur.

## 10.2. Yerleşim Planı Yükleme

Admin:

1. Yerleşim Planı Yükle düğmesine basar.
2. Tesis veya laboratuvar görselini seçer.
3. Port işaretlerini sürükleyerek doğru konuma taşır.
4. Yerleşimi kaydeder.

Operator yerleşimi görüntüleyebilir ancak yönetici yetkisi gerektiren değişiklikleri yapamaz.

## 10.3. Reçete Atama

1. Sol listeden portu seçin.
2. Reçete Ata düğmesine basın.
3. Aktif reçetelerden doğru olanı seçin.
4. Onaylayın.
5. Port satırındaki reçete bilgisini kontrol edin.

## 10.4. Port Silme

Seçili Portu Sil işlemi Admin yetkisi gerektirir. Silmeden önce portun aktif batch'te kullanılmadığını ve RFID eşlemesinin gerçekten kaldırılması gerektiğini doğrulayın.

# 11. GLT Batch Yönetimi

## 11.1. GLT Batch'in Amacı

GLT Batch, önceden seçilmiş bir port grubunun test sonuçlarını tek oturum altında toplar. Her port Bekleniyor, Geçti veya Kaldı durumunda izlenir.

## 11.2. Batch Şablonu Oluşturma

Admin veya Supervisor:

1. GLT > Batch sekmesini açar.
2. Şablon Kaydet düğmesine basar.
3. Benzersiz bir şablon adı yazar.
4. Liste içinden batch'e dahil edilecek portları işaretler.
5. Gerekirse Tümünü Seç seçeneğini kullanır.
6. Onay sonrası kendi parolasını girer.
7. Başarı mesajında port sayısını kontrol eder.

Şablon, üretim hattı veya ürün ailesi için tekrar kullanılabilir port grubu sağlar.

## 11.3. Şablon Silme

Şablon Sil işlemi Admin veya Supervisor yetkisi ve parola doğrulaması gerektirir. Silmeden önce aktif ve planlı batch'lerde kullanılmadığını doğrulayın.

## 11.4. Yeni GLT Batch Başlatma

1. Yeni Batch Başlat düğmesine basın.
2. Kayıtlı şablonu seçin.
3. FAIL testleri rapora dahil et seçeneğini ihtiyaca göre belirleyin.
4. Batch adını yazın.
5. Kullanıcı parolanızı girerek işlemi onaylayın.
6. Otomatik eklenen tarih/saat ile tam batch adını kontrol edin.
7. Port tablosunda tüm beklenen portların yer aldığını doğrulayın.

## 11.5. Test Sonuçlarının Güncellenmesi

Batch aktifken RFID ile eşleşen her tamamlanmış test ilgili portu otomatik günceller:

- Bekleniyor: Henüz geçerli test sonucu yok
- Geçti: PASS
- Kaldı: FAIL

Harita üzerindeki port renkleri de batch durumuna göre değişir.

## 11.6. Batch Bitirme

Batch Bitir düğmesine basıldığında:

1. FAIL veya test edilmemiş port sayısı gösterilir.
2. Devam edilirse kullanıcı parolası doğrulanır.
3. Her FAIL port için açıklama istenir.
4. Test edilmemiş portlara Test yapılmadı açıklaması atanır.
5. Batch tamamlanır.
6. Bireysel test PDF'leri batch klasörüne kopyalanır.
7. Batch özet PDF'i oluşturulur.
8. Batch zaman aralığına ait Audit Trail PDF'i batch klasörüne eklenir.
9. PDF uygulama içinde açılır.

Tüm portlar tamamlandığında sistem otomatik batch tamamlama akışını da çalıştırabilir.

# 12. Test Reçeteleri

## 12.1. Reçete Listesi

Reçete sekmesinde reçete adı, aktif/pasif durumu, hedef basınç, süreler, kritik limitler ve açıklama görüntülenir.

Butonlar:

- Yeni Reçete
- Düzenle
- Aktif Yap
- Pasif Yap

Bu değişiklikler Admin veya Supervisor yetkisi gerektirir.

## 12.2. Reçete Parametreleri

p1 - Maksimum Şişirme Süresi (sn): Eldivenin hedef basınca ulaşması için izin verilen en uzun süre.

p2 - Hedef Test Basıncı (Pa): Şişirme sonunda ulaşılması gereken hedef basınç.

p3 - Stabilizasyon Süresi (sn): Ölçüm öncesi basıncın dengelenmesi için bekleme süresi.

p4 - Yeniden Şişirme Tetikleme Eşiği (Pa): Stabilizasyon sırasında yeniden şişirmeyi tetikleyen basınç farkı/eşiği.

p6 - Kritik Basınç Düşüş Eşiği (Pa): Kritik düşüş değerlendirmesinde kullanılan sınır.

p7 - Sızdırmazlık İzleme Süresi (sn): Basınç düşüşünün değerlendirildiği ölçüm süresi. Yazılım arayüzünde en fazla 120 saniye seçilebilir.

p8 - Kabul Edilebilir Basınç Düşüş Limiti (Pa): PASS/FAIL değerlendirmesinde kullanılan kabul limiti.

NOT: Uygulamanın güncel doğrulama kuralına göre p8 değeri p6 değerinden küçük olamaz. Kaydetme öncesi ekrandaki hata ve teorik süre uyarıları dikkate alınmalıdır.

## 12.3. Yeni Reçete Oluşturma

1. Yeni Reçete düğmesine basın.
2. Benzersiz Reçete Adı yazın.
3. p1, p2, p3, p4, p6, p7 ve p8 değerlerini girin.
4. Sağdaki grafikte şişirme, stabilizasyon ve ölçüm eğrisini inceleyin.
5. Açıklama alanına amaç ve kullanım kapsamını yazın.
6. Teorik Maksimum Test Süresi bilgisini kontrol edin.
7. OK düğmesine basın.
8. Beş saniyelik geri sayım tamamlandıktan sonra Kaydet düğmesine basın.

Reçete oluşturma veya değiştirme geri alınamaz bir üretim parametresi değişikliği olarak değerlendirilmelidir.

## 12.4. Reçeteyi Aktif/Pasif Yapma

Aktif reçeteler yeni port atamalarında ve testlerde seçilebilir. Pasif reçeteler geçmiş kayıtlar için korunur ancak yeni kullanımda listelenmeyebilir.

Bir reçeteyi pasife almadan önce bağlı portları ve planlı batch'leri kontrol edin.

# 13. Test Raporları ve Elektronik İmza

## 13.1. Rapor Sekmesi

Rapor sekmesi tamamlanmış test kayıtlarını filtreler ve yönetir. RUNNING durumundaki kayıtlar listede gösterilmez.

Filtreler:

- Test ID
- Başlangıç tarihi
- Bitiş tarihi
- Search

Tablo sütunları:

- Test ID
- RFID
- Batch
- Reçete
- Tarih
- Saat
- Durum
- Sonuç
- Eylemler

## 13.2. PDF Test Raporu

1. Bir test satırı seçin.
2. Rapor Dili alanından Türkçe veya English seçin.
3. Generate PDF düğmesine basın.
4. Oluşturulan raporu uygulama içi PDF görüntüleyicide kontrol edin.

Satıra çift tıklamak da seçili test için PDF üretme/açma işlemini başlatabilir.

## 13.3. Rapor ve Batch Klasörleri

Rapor Klasörünü Aç, bireysel test PDF'lerinin bulunduğu klasörü açar.

Batch Klasörünü Aç, batch özetleri, kopyalanan test raporları ve batch Audit Trail raporlarının bulunduğu klasörü açar.

## 13.4. Elektronik İmza

1. İmzalanacak test kaydını seçin.
2. Apply Signature düğmesine basın.
3. İmza anlamını yazın; örneğin Reviewed by veya Approved by.
4. Kimlik doğrulaması için kendi parolanızı tekrar girin.
5. Başarı mesajını kontrol edin.
6. PDF raporunu yeniden oluşturup imza bilgisinin raporda yer aldığını doğrulayın.

Elektronik imza başka kullanıcı adına atılamaz. Parola paylaşımı yasaktır.

## 13.5. Teste Ait Audit Trail

View Audit Trail düğmesi tarih aralığı seçerek Audit Trail PDF'i üretir. Test işlemini etkileyen kullanıcı, reçete, batch, bağlantı ve rapor olayları gerektiğinde merkezi Audit Trail sekmesinden ayrıca incelenmelidir.

# 14. Audit Trail

## 14.1. Ekranın Amacı

Audit Trail sekmesi kullanıcı, GLT, ORABS, LAF ve sistem olaylarını merkezi olarak gösterir. Her kayıt zaman, kullanıcı, kategori, işlem ve açıklama bilgisi içerir.

## 14.2. Kategori Filtreleri

- Hepsi: Tüm kategoriler
- Kullanıcı: Giriş, çıkış, parola ve kullanıcı yönetimi olayları
- GLT: GLT olayları ile ilgili kullanıcı olayları
- ORABS: ORABS ve LAF olayları ile ilgili kullanıcı olayları

## 14.3. Tarih Filtresi

1. Başlangıç ve Bitiş tarihini seçin.
2. Kategori filtresini seçin.
3. Filtrele düğmesine basın.
4. Kayıtları kronolojik olarak inceleyin.

## 14.4. PDF Raporu

Görüntülenen filtre sonucunu PDF'e aktarmak için PDF Raporu düğmesine basın. Kayıt yoksa rapor üretilemez.

Audit Trail kayıtları normal kullanıcı arayüzünden düzenlenemez veya silinemez.

# 15. Kullanıcı Yönetimi

## 15.1. Kullanıcı Sekmesi

Kullanıcı sekmesi yalnız Admin'e görünür. Kullanıcı listesinde:

- ID
- Kullanıcı Adı
- Tam İsim
- Rol
- E-posta
- Durum

Butonlar:

- Yenile
- Yeni Kullanıcı
- Düzenle
- Şifre
- Aktif/Pasif

## 15.2. Yeni Kullanıcı

1. Yeni Kullanıcı düğmesine basın.
2. Benzersiz Kullanıcı Adı girin.
3. Tam İsim ve E-posta bilgilerini yazın.
4. Operator, Supervisor veya Admin rolünü seçin.
5. Parola politikasına uygun geçici parola girin.
6. OK düğmesine basın.
7. Kullanıcıya ilk girişte parolasını değiştirmesi gerektiğini bildirin.

Kullanıcı hesabı kişiye özel olmalıdır. Ortak hesap kullanımı izlenebilirliği bozar.

## 15.3. Kullanıcı Düzenleme

Düzenle penceresinde kullanıcı adı değiştirilemez. Tam İsim, E-posta ve Rol güncellenebilir.

Rol yükseltme işlemi minimum yetki prensibine göre yapılmalıdır.

## 15.4. Parola Sıfırlama

1. Kullanıcıyı seçin.
2. Şifre düğmesine basın.
3. Eski paroladan farklı, politika uyumlu yeni parola girin.
4. Kullanıcıya yeni geçici parolayı güvenli kanaldan iletin.

Parola sıfırlama Audit Trail'e kaydedilir.

## 15.5. Hesabı Aktif/Pasif Yapma

Pasif kullanıcı giriş yapamaz. Hatalı giriş nedeniyle pasif olan hesabı açmak için ilgili kullanıcıyı seçip Aktif/Pasif düğmesini kullanın.

Ana admin hesabı pasif yapılamaz.

# 16. Sistem, GLT ve ORABS Ayarları

## 16.1. Genel Ayarlar

Dil / Language: Arayüz dilini Türkçe veya İngilizce yapar. Bazı donanım ve teknik alanlar uygulama kaynak koduna bağlı olarak tek dilde kalabilir.

## 16.2. Depolama Klasörü

Admin, veritabanı, reports, batches ve denetim izi dosyalarının temel klasörünü seçebilir.

Klasör değişikliğinden sonra:

- Yeni klasörün yazılabilir olduğunu doğrulayın.
- Gerekli alt klasörlerin oluştuğunu kontrol edin.
- Uygulamayı yeniden başlatın.
- Eski verinin taşınması gerekiyorsa onaylı yedekleme/taşıma prosedürü uygulayın.

Depolama yolu değiştirmek mevcut veriyi otomatik olarak yeni konuma taşımayabilir.

## 16.3. Güvenlik Ayarları

Oturum Zaman Aşımı: 1 ile 120 dakika arasında otomatik çıkış süresi.

Periyodik Şifre Değiştirme: 3, 6, 9 veya 12 ay.

Rapor Ayarları:

- Şirket Adı
- GLT Rapor Başlığı
- Batch Rapor Başlığı
- Audit Rapor Başlığı
- Rapor Logosu

Yeni rapor ayarları sonraki PDF üretiminde geçerli olur.

## 16.4. GLT Ayarları

GLT Ayarları'nda raporlarda ve uygulama başlığında kullanılacak logo yönetilir. PNG veya JPG dosyası seçilebilir; dosya boyutu 5 MB'ı aşmamalıdır.

Giriş ekranındaki LCC marka logosu sabittir; rapor logosu değişikliği giriş logosunu değiştirmez.

## 16.5. ORABS 3B Model Ayarları

Admin aşağıdaki ayarları yapabilir:

- GLB veya GLTF model dosyası
- Model birimi: Milimetre, Santimetre veya Metre
- Genel Bakış yönleri: Ön, Arka, Sol, Sağ
- Genel Bakış'ta LAF kartının görünürlüğü

Yanlış model birimi kapı/port yerleşimini ve görünümü bozabilir. Model değiştirildiğinde kapı/port sayıları ve eşlemeleri yeniden doğrulanmalıdır.

## 16.6. Weidmüller Bağlantı Ayarları

- IP Adresi
- Modbus TCP portu; standart değer genellikle 502
- Polling süresi
- IO Eşleme Dosyası
- IO Modüllerini Düzenle

IP, port veya polling değişikliği kaydedildiğinde IO çalışanları yeni ayarlarla yeniden başlatılır.

## 16.7. Port, Bariyer ve LAF Ayarları

Port İsimleri / Hareket Sensörü: ORABS eldiven port adlarını ve hareket sensörü özelliklerini düzenler.

Işık Bariyerlerini Düzenle: Bir bariyerin bağlı olduğu kapıları ve interlock davranışını tanımlar.

Bariyer Sensörlerini Düzenle: Kablosuz IR sensör MAC/kimlik ve port eşlemelerini yönetir.

LAF:

- COM Portu
- Baud
- Slave ID
- Polling süresi
- Snapshot periyodu
- LAF Sensörlerini Düzenle

LAF sensör editöründe cihaz dokümanına uygun register adresi, veri tipi, birim, ölçek, offset ve alarm limitleri tanımlanmalıdır.

## 16.8. IO Modülleri ve Noktaları

IO Modüllerini Düzenle ekranında:

- Modül adı
- IP/host
- Port
- Unit ID
- Polling
- Aktif/Pasif
- Açıklama
- Coupler'dan Tara

IO Noktalarını Düzenle ekranında:

- Tip: DI, DO, AI veya AO
- Kanal
- Etiket
- Görünürlük
- Açıklama
- Fiziksel hedef bağlantısı

Bağlantı tipleri:

- Kapı
- Kapı Grubu
- Port
- LAF Sensörü
- Işık Bariyeri
- Acil Stop

Rol alanına sensor, motor, kilit veya led gibi açıklayıcı bir görev yazılabilir.

## 16.9. Sekme Görünürlüğü

Admin şu sekmeleri gösterebilir veya gizleyebilir:

- ORABS
- GLT
- Kullanıcı
- Audit Trail
- ORABS Genel Bakış
- ORABS Batch
- ORABS LAF
- ORABS IO

Ayarlar sekmeleri her zaman görünür kalır. Kritik bir sekmeyi gizlemeden önce kullanıcı iş akışının etkilenmediğini doğrulayın.

# 17. Veri Saklama ve Rapor Arşivi

## 17.1. Temel Veri Türleri

Sistem aşağıdaki kayıtları saklar:

- Kullanıcı ve rol kayıtları
- Reçeteler
- RFID ve port eşlemeleri
- Test kayıtları ve basınç verileri
- GLT ve ORABS batch kayıtları
- Elektronik imzalar
- Audit Trail
- LAF snapshot ve alarm kayıtları
- ORABS kapı, port, bariyer ve IO eşlemeleri
- PDF ve CSV raporları

## 17.2. Klasör Yapısı

Seçilen depolama temelinde tipik olarak şu klasörler kullanılır:

- database: SQLite veritabanı
- reports: Bireysel test ve Audit Trail raporları
- batches: Batch klasörleri, özet raporlar ve ilgili test PDF'leri

## 17.3. Yedekleme

Yedekleme sırasında:

1. Aktif test veya batch olmadığını doğrulayın.
2. Uygulamayı güvenli biçimde kapatın.
3. Veritabanı ile reports ve batches klasörlerini birlikte yedekleyin.
4. Yedek dosyasının tarihini ve bütünlüğünü doğrulayın.
5. Geri yükleme testlerini kurumun doğrulama prosedürüne göre yapın.

Çalışan SQLite dosyasını kontrolsüz kopyalamak tutarsız yedek oluşturabilir.

# 18. Günlük Operatör İş Akışı

## 18.1. Vardiya Başlangıcı

1. PC, USB ana cihaz, IO ağı ve LAF bağlantılarını kontrol edin.
2. Kendi kullanıcı adınız ve parolanızla giriş yapın.
3. ORABS Genel Bakış'ta alarm şeridi olmadığını kontrol edin.
4. 3B modelde sarı veya turuncu beklenmeyen kapı olmadığını kontrol edin.
5. LAF değerlerinin güncel ve limit içinde olduğunu doğrulayın.
6. Bağlı GLT Cihazları kartlarını ve batarya seviyelerini kontrol edin.
7. Doğru batch konfigürasyonunu ve üretim emrini doğrulayın.

## 18.2. Batch ve Test

1. Batch adını kurumsal adlandırma kuralına göre yazın.
2. Doğru ORABS konfigürasyonunu veya GLT şablonunu seçin.
3. Batch'i başlatın.
4. Kapıların 3B ve fiziksel durumunu karşılaştırın.
5. GLT cihazını doğru porta yerleştirin.
6. RFID, port ve reçeteyi doğrulayın.
7. Mount işlemini yapın.
8. Testi başlatın ve canlı grafiği izleyin.
9. PASS/FAIL sonucunu ve batch tablosunu kontrol edin.
10. Dismount sırasında cihazı tutun ve güvenlik kodunu girin.
11. Diğer portlar için işlemi tekrarlayın.

## 18.3. Vardiya veya Batch Sonu

1. Bekleyen ve FAIL portları kontrol edin.
2. FAIL açıklamalarını yazın.
3. Batch'i bitirin.
4. Özet PDF ve Audit Trail PDF'ini kontrol edin.
5. Gerekliyse elektronik imza uygulayın.
6. Raporların doğru klasörde oluştuğunu doğrulayın.
7. Güvenli Çıkış Yap işlemini uygulayın.

# 19. Sorun Giderme

## 19.1. Giriş Yapılamıyor

Olası nedenler:

- Kullanıcı adı veya parola yanlış
- Hesap üç hatalı deneme sonrası pasif
- Parola süresi dolmuş
- Kullanıcı aktif değil

Çözüm:

- Büyük/küçük harf ve klavye dilini kontrol edin.
- Parola süresi doldu penceresinde yeni parola belirleyin.
- Hesap pasifse Admin'e başvurun.
- Ortak veya başka kullanıcıya ait hesap kullanmayın.

## 19.2. GLT COM Bağlantısı Kurulamıyor

- USB kablosunu ve ana cihazın enerjisini kontrol edin.
- Windows Aygıt Yöneticisi'nde COM portunu kontrol edin.
- Port listesini yenileyin ve doğru portu seçin.
- Portu kullanan başka seri terminal uygulamasını kapatın.
- Kes ve tekrar Bağlan işlemini deneyin.
- Otomatik Bağlan yanlış portu seçiyorsa manuel port seçin.

## 19.3. GLT Cihaz Kartı Görünmüyor

- COM bağlantısının Bağlı olduğunu kontrol edin.
- Cihazın enerjisini, bataryasını ve kablosuz haberleşmesini kontrol edin.
- Birkaç saniye keşif süresini bekleyin.
- Sistem loglarında HELLO/STREAM veya zaman aşımı mesajlarını inceleyin.
- Manuel senkronizasyonu yalnız kart göründükten sonra kullanın.

## 19.4. Kontrol Düğmeleri Pasif

Mount, Dismount, Başlat ve İptal düğmeleri yalnız tanımlı RFID okunduğunda etkinleşir.

- RFID'nin kartta göründüğünü kontrol edin.
- Yeni RF ID ise Port Kaydet işlemini tamamlayın.
- Porta aktif reçete atandığını kontrol edin.
- Senkronizasyonun tamamlanmasını bekleyin.

## 19.5. RFID Tanınmıyor veya Yanlış Porta Gidiyor

- Port/RFID kaydını GLT Yerleşim Planı'nda kontrol edin.
- Aynı RFID'nin birden fazla kaydı olmadığını doğrulayın.
- Cihaz kartından Manuel Senkronizasyon çalıştırın.
- ORABS 3B port eşlemesini ayrıca kontrol edin; GLT port kaydı ile ORABS 3B eşlemesi farklı tablolardır.

## 19.6. 3B Model Görünmüyor

- ORABS Ayarları'nda doğru GLB/GLTF dosyasını seçin.
- Dosyanın yerel olarak erişilebilir olduğunu kontrol edin.
- Model birimini doğrulayın.
- Uygulamayı yeniden başlatın.
- Model düğüm adları değiştiyse kapı ve port eşlemelerini yeniden kontrol edin.

## 19.7. IO Modülü Bağlı Değil

- Modül IP adresi, port 502 ve unit ID'yi kontrol edin.
- PC ile modülün aynı ağda olduğunu doğrulayın.
- Güvenlik duvarı ve VLAN erişimini kontrol edin.
- Coupler'dan Tara düğmesini kullanın.
- IO ekranında Modülleri Yenile düğmesine basın.
- Donanım ayarı değiştiyse worker yeniden başlatmasının tamamlanmasını bekleyin.

## 19.8. LAF Değeri Gelmiyor

- COM portu, baud ve slave ID'yi kontrol edin.
- Register adresi ve veri tipinin cihaz dokümanıyla uyumlu olduğunu doğrulayın.
- LAF sekmesinde Yenile düğmesine basın.
- Aynı COM portunu kullanan başka uygulamayı kapatın.
- Sensörün Görünür ve Aktif olduğunu kontrol edin.

## 19.9. Kapı Beklenmedik Renkte

- Kırmızı/yeşil renk batch konfigürasyonundan gelir.
- Sarı renk fiziksel DI açık sensöründen gelir ve batch renginin üzerine yazılır.
- Turuncu renk aktif ışık bariyerinden gelir ve diğer renklerin üzerine yazılır.
- Gri kapı IO'ya bağlı olmayabilir veya batch dışında olabilir.

Önce fiziksel durumu kontrol edin, sonra kapı grubu ve IO eşlemesini inceleyin.

## 19.10. Batch Başlatılamıyor

- Başka aktif batch olup olmadığını kontrol edin.
- Batch adının boş olmadığını doğrulayın.
- Aktif ve geçerli konfigürasyon/şablon seçin.
- ORABS konfigürasyonunda kapı grubu ve port bulunduğunu kontrol edin.
- GLT batch için önce şablon oluşturun.
- Parola doğrulamasını kendi hesabınızla yapın.

## 19.11. PDF Oluşmuyor veya Açılmıyor

- Depolama klasörünün yazılabilir olduğunu kontrol edin.
- Disk alanını kontrol edin.
- Rapor ve batch klasörlerinin varlığını kontrol edin.
- Doğru test kaydının seçili olduğunu doğrulayın.
- Uygulama içi görüntüleyici açılmazsa PDF'nin klasörde oluşup oluşmadığını kontrol edin.
- Dosya başka uygulamada kilitliyse kapatıp tekrar deneyin.

## 19.12. Audit Trail Kaydı Bulunamıyor

- Tarih aralığını genişletin.
- Bitiş tarihinin olaydan sonraki günü kapsadığını kontrol edin.
- Hepsi kategorisini seçin.
- ORABS filtresinin LAF ve kullanıcı olaylarını da içerdiğini unutmayın.

# 20. Güvenli Kapatma

## 20.1. Oturum Kapatma

Günlük kullanım sonunda sağ üstte Çıkış Yap düğmesine basın. Bu işlem kullanıcı oturumunu kapatır ve uygulamayı kilitli moda geçirir. Canlı ORABS izleme arka planda devam edebilir.

## 20.2. Uygulamayı Tamamen Kapatma

Uygulamayı tamamen kapatmadan önce:

1. Devam eden GLT testini tamamlayın veya onaylı şekilde iptal edin.
2. Aktif batch'i tamamlayın veya prosedüre göre duraklatın.
3. Raporların oluştuğunu kontrol edin.
4. Cihazları güvenli şekilde dismount edin.
5. Admin veya Supervisor pencere kapatma düğmesini kullanın.

Arka plan LAF ve IO çalışanlarının düzgün kapanması için uygulamayı görev yöneticisinden zorla kapatmayın. Zorunlu kapanma yaşanırsa yeniden açılışta aktif batch, rapor ve Audit Trail kayıtları kontrol edilmelidir.

# Ek A. Hızlı Durum Sözlüğü

PASS: Test kabul kriterlerini karşıladı.

FAIL: Test kabul kriterlerini karşılamadı.

PENDING / Bekleniyor: Batch portu için geçerli sonuç yok.

ABANDONED: Test tamamlanmadan bırakıldı veya iptal edildi.

RUNNING: İşlem devam ediyor.

PAUSED: Batch duraklatılmış durumda.

COMPLETED: İşlem tamamlandı.

LOCKED / Kilitli: Kapı veya hesap bağlama göre kilitli durumda.

OFFLINE / Bağlantı Yok: Cihaz veya modül haberleşmiyor.

# Ek B. Doküman Bakım Notu

Bu metin 30.07.2026 tarihindeki yazılım kaynak koduna göre hazırlanmıştır. Arayüz, kullanıcı rolleri, test parametreleri, donanım bağlantıları veya rapor formatı değiştirildiğinde kılavuz revize edilmelidir.
