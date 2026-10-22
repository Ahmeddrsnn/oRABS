#pragma once

#include <Arduino.h>
#include <LittleFS.h>

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// TEST KAYIT SİSTEMİ — LittleFS Flash Depolama
// ═══════════════════════════════════════════════════════════════════
// Her test sonucu ayrı bir dosyada saklanır: /tests/XXXX.bin
// Index dosyası: /tests/index.bin (hızlı erişim)
// Basınç zaman serisi test dosyasının içinde (1Hz kayıt)
// ═══════════════════════════════════════════════════════════════════

/// Kolayca değiştirilebilir sabitler
static constexpr int MAX_STORED_TESTS = 10;       // Flash'ta tutulacak maks test
static constexpr int MAX_PRESSURE_SAMPLES = 600;   // Maks basınç örneği (1Hz × 600sn)
static constexpr uint32_t STORAGE_MAGIC = 0x474C54; // "GLT" magic number

/// Test başarısızlık nedenleri
enum class TestFailReason : uint8_t {
  PASS = 0,
  CRITICAL_DROP = 1,       // Toplam düşüş > P8
  INFLATION_TIMEOUT = 2,   // Şişirme zaman aşımı
  ABORTED = 3              // Kullanıcı tarafından iptal edildi
};

/// Tek bir test kaydının header bilgisi (sabit boyutlu)
struct __attribute__((packed)) TestRecordHeader {
  uint32_t magic;               // Doğrulama: 0x474C54
  uint32_t testId;              // Oto-artan ID
  uint32_t rfidTag;             // RFID kartı UID
  uint16_t portNumber;          // Port numarası (encoded: left<<8|right)
  char     operatorName[32];    // Kim yaptı
  char     recipeName[16];      // Reçete adı
  
  // Zaman bilgileri (RTC'den)
  uint8_t  startYear;           // 2000 + year
  uint8_t  startMonth;
  uint8_t  startDay;
  uint8_t  startHour;
  uint8_t  startMinute;
  uint8_t  startSecond;
  
  uint16_t durationSec;         // Toplam test süresi (saniye)
  
  // Basınç verileri
  int16_t  startPressure;       // Başlangıç basıncı (Pa)
  int16_t  endPressure;         // Bitiş basıncı (Pa)
  int16_t  maxPressure;         // Maksimum basınç (Pa)
  int16_t  totalDrop;           // Toplam düşüş (Pa)
  int16_t  windowDrop;          // Pencere düşüşü (Pa)
  
  // Reçete parametreleri (sonuçla birlikte sakla)
  int16_t  targetPressure;      // Hedef basınç (Pa) - p2
  int16_t  acceptableDrop;      // Kabul edilebilir düşüş (Pa) - p6
  int16_t  criticalDrop;        // Kritik düşüş sınırı (Pa) - p8
  int16_t  windowSize;          // Pencere boyutu (sn) - p7
  
  // Ek reçete parametreleri
  int16_t  inflationMaxTime;    // Şişirme max süresi (sn) - p1
  int16_t  stabilizationTime;   // Dengeleme süresi (sn) - p3
  
  // Sonuç
  uint8_t  passed;              // 1=PASS, 0=FAIL
  uint8_t  failReason;          // TestFailReason enum
  
  // Basınç zaman serisi bilgisi
  uint16_t sampleCount;         // Kaç basınç örneği kaydedildi
  
  // v2: Yeni alan (eski kayıtlarda 0 olarak okunur)
  int16_t  reinflateThreshold;  // Yeniden şişirme eşiği (Pa) - p4
};

/// Index dosyası (Flash'taki test listesi)
struct __attribute__((packed)) TestStorageIndex {
  uint32_t magic;
  uint32_t nextTestId;          // Sonraki test ID'si (oto-artan)
  uint16_t testCount;           // Kayıtlı test sayısı
  uint16_t fileIds[MAX_STORED_TESTS]; // Dosya ID'leri (test_XXXX.bin)
};

/// Singleton Test Depolama Servisi
class TestStorageService {
public:
  static TestStorageService& getInstance() {
    static TestStorageService instance;
    return instance;
  }
  
  /// LittleFS üzerinde /tests/ klasörünü hazırla, index oku
  bool init();
  
  /// Test sonucunu kaydet (header + basınç serisi)
  /// @param header Test metadata
  /// @param samples Basınç zaman serisi dizisi
  /// @param sampleCount Dizi uzunluğu
  /// @return kayıt ID'si, hata durumunda 0
  uint32_t saveTest(const TestRecordHeader& header, 
                    const int16_t* samples, uint16_t sampleCount);
  
  /// Kayıtlı test sayısı
  uint16_t getTestCount() const { return index_.testCount; }
  
  /// Flash dolu mu? (test sayısı >= MAX_STORED_TESTS)
  bool isStorageFull() const { return index_.testCount >= MAX_STORED_TESTS; }
  
  /// Kalan test kapasitesi
  uint16_t getRemainingCapacity() const { 
    return (index_.testCount < MAX_STORED_TESTS) 
           ? (MAX_STORED_TESTS - index_.testCount) : 0; 
  }
  
  /// Belirli bir testi oku (PC'ye aktarım için)
  /// @param index 0-based index (0 = en eski)
  /// @param headerOut Header verisini buraya yazar
  /// @param samplesOut Basınç verisini buraya yazar (null olabilir)
  /// @param maxSamples samplesOut dizisinin max boyutu
  /// @return başarılı mı
  bool readTest(uint16_t index, TestRecordHeader& headerOut,
                int16_t* samplesOut = nullptr, uint16_t maxSamples = 0);
  
  /// Tüm kayıtları sil (PC'ye aktarım sonrası)
  bool clearAll();
  
  /// Depolama istatistikleri (buffer'a JSON yaz, yazılan byte döner)
  int getStorageInfoJson(char* buf, size_t bufSize);
  
  /// Sonraki test ID'si (peek — kaydetmeden)
  uint32_t getNextTestId() const { return index_.nextTestId; }

private:
  TestStorageService() = default;
  
  TestStorageIndex index_;
  bool initialized_ = false;
  
  /// Index dosyasını oku
  bool loadIndex();
  
  /// Index dosyasını yaz
  bool saveIndex();
  
  /// Test dosya yolunu oluştur
  String getTestFilePath(uint16_t fileId);
  
  // Silme/Kopyalama yasak
  TestStorageService(const TestStorageService&) = delete;
  TestStorageService& operator=(const TestStorageService&) = delete;
};

} // namespace GLT
