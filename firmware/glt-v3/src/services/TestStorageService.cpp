#include "services/TestStorageService.h"
#include "core/Logger.h"

namespace GLT {

// ═══════════════════════════════════════════════════════════════════
// DOSYA YOLLARI
// ═══════════════════════════════════════════════════════════════════
static const char* TESTS_DIR    = "/tests";
static const char* INDEX_FILE   = "/tests/index.bin";

// ═══════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════
bool TestStorageService::init() {
  if (initialized_) return true;
  
  // /tests/ klasörünü oluştur (yoksa)
  if (!LittleFS.exists(TESTS_DIR)) {
    LittleFS.mkdir(TESTS_DIR);
    LOG_INFO(LogCategory::CORE, "TestStorage: /tests/ klasörü oluşturuldu");
  }
  
  // Index dosyasını yükle (yoksa oluştur)
  if (!loadIndex()) {
    // Yeni index oluştur
    memset(&index_, 0, sizeof(index_));
    index_.magic = STORAGE_MAGIC;
    index_.nextTestId = 1;
    index_.testCount = 0;
    
    if (!saveIndex()) {
      LOG_ERROR(LogCategory::CORE, "TestStorage: Index dosyası oluşturulamadı!");
      return false;
    }
    LOG_INFO(LogCategory::CORE, "TestStorage: Yeni index dosyası oluşturuldu");
  }
  
  initialized_ = true;
  LOG_INFO(LogCategory::CORE, "TestStorage: Başlatıldı (%d/%d test kayıtlı)", 
           index_.testCount, MAX_STORED_TESTS);
  return true;
}

// ═══════════════════════════════════════════════════════════════════
// TEST KAYDET
// ═══════════════════════════════════════════════════════════════════
uint32_t TestStorageService::saveTest(const TestRecordHeader& header, 
                                      const int16_t* samples, 
                                      uint16_t sampleCount) {
  if (!initialized_) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Başlatılmadı!");
    return 0;
  }
  
  // Kapasite kontrolü
  if (isStorageFull()) {
    LOG_WARN(LogCategory::CORE, "TestStorage: Flash DOLU! (%d/%d)", 
             index_.testCount, MAX_STORED_TESTS);
    return 0;
  }
  
  // Test ID'si ata
  uint32_t testId = index_.nextTestId;
  uint16_t fileId = (uint16_t)(testId & 0xFFFF);
  
  // Header'ı kopyala ve ID'yi ayarla
  TestRecordHeader rec = header;
  rec.magic = STORAGE_MAGIC;
  rec.testId = testId;
  rec.sampleCount = sampleCount;
  
  // Dosya yolu
  String filePath = getTestFilePath(fileId);
  
  // Dosyayı yaz
  File f = LittleFS.open(filePath, "w");
  if (!f) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Dosya açılamadı: %s", filePath.c_str());
    return 0;
  }
  
  // 1. Header yaz
  size_t written = f.write((const uint8_t*)&rec, sizeof(TestRecordHeader));
  if (written != sizeof(TestRecordHeader)) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Header yazma hatası!");
    f.close();
    LittleFS.remove(filePath);
    return 0;
  }
  
  // 2. Basınç verisi yaz
  if (samples && sampleCount > 0) {
    size_t dataSize = sampleCount * sizeof(int16_t);
    written = f.write((const uint8_t*)samples, dataSize);
    if (written != dataSize) {
      LOG_ERROR(LogCategory::CORE, "TestStorage: Basınç verisi yazma hatası!");
      f.close();
      LittleFS.remove(filePath);
      return 0;
    }
  }
  
  f.close();
  
  // 3. Index güncelle
  index_.fileIds[index_.testCount] = fileId;
  index_.testCount++;
  index_.nextTestId++;
  
  if (!saveIndex()) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Index güncelleme hatası!");
    // Dosyayı da sil — tutarsızlık olmasın
    LittleFS.remove(filePath);
    index_.testCount--;
    index_.nextTestId--;
    return 0;
  }
  
  LOG_INFO(LogCategory::CORE, 
           "TestStorage: Test #%lu kaydedildi (%u örnek, %s) [%d/%d]",
           testId, sampleCount, rec.passed ? "PASS" : "FAIL",
           index_.testCount, MAX_STORED_TESTS);
  
  return testId;
}

// ═══════════════════════════════════════════════════════════════════
// TEST OKU
// ═══════════════════════════════════════════════════════════════════
bool TestStorageService::readTest(uint16_t index, TestRecordHeader& headerOut,
                                  int16_t* samplesOut, uint16_t maxSamples) {
  if (!initialized_ || index >= index_.testCount) {
    return false;
  }
  
  uint16_t fileId = index_.fileIds[index];
  String filePath = getTestFilePath(fileId);
  
  File f = LittleFS.open(filePath, "r");
  if (!f) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Dosya okunamadı: %s", filePath.c_str());
    return false;
  }
  
  // Header oku (memset ile yeni alanlar 0'dan başlar — eski kayıtlar uyumlu)
  memset(&headerOut, 0, sizeof(TestRecordHeader));
  size_t readBytes = f.read((uint8_t*)&headerOut, sizeof(TestRecordHeader));
  // Eski kayıtlar 2 byte kısa olabilir (reinflateThreshold alanı yoktu)
  if (readBytes < sizeof(TestRecordHeader) - 2) {
    f.close();
    return false;
  }
  
  // Magic doğrula
  if (headerOut.magic != STORAGE_MAGIC) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Geçersiz magic: 0x%06X", headerOut.magic);
    f.close();
    return false;
  }
  
  // Basınç verisi oku (isteniyorsa)
  if (samplesOut && maxSamples > 0 && headerOut.sampleCount > 0) {
    uint16_t toRead = min(headerOut.sampleCount, maxSamples);
    f.read((uint8_t*)samplesOut, toRead * sizeof(int16_t));
  }
  
  f.close();
  return true;
}

// ═══════════════════════════════════════════════════════════════════
// TÜM KAYITLARI SİL
// ═══════════════════════════════════════════════════════════════════
bool TestStorageService::clearAll() {
  if (!initialized_) return false;
  
  // Tüm test dosyalarını sil
  for (uint16_t i = 0; i < index_.testCount; i++) {
    String filePath = getTestFilePath(index_.fileIds[i]);
    if (LittleFS.exists(filePath)) {
      LittleFS.remove(filePath);
    }
  }
  
  // Index sıfırla (nextTestId korunur — tekrar aynı ID kullanılmasın)
  uint32_t preservedNextId = index_.nextTestId;
  memset(&index_, 0, sizeof(index_));
  index_.magic = STORAGE_MAGIC;
  index_.nextTestId = preservedNextId;
  index_.testCount = 0;
  
  if (!saveIndex()) {
    LOG_ERROR(LogCategory::CORE, "TestStorage: Temizleme sonrası index hatası!");
    return false;
  }
  
  LOG_INFO(LogCategory::CORE, "TestStorage: Tüm kayıtlar silindi. Sonraki ID: %lu", 
           preservedNextId);
  return true;
}

// ═══════════════════════════════════════════════════════════════════
// DEPOLAMA BİLGİSİ (JSON)
// ═══════════════════════════════════════════════════════════════════
int TestStorageService::getStorageInfoJson(char* buf, size_t bufSize) {
  return snprintf(buf, bufSize,
      "{\"test_count\":%d,\"max_tests\":%d,\"remaining\":%d,"
      "\"is_full\":%s,\"next_id\":%lu,"
      "\"flash_total\":%lu,\"flash_used\":%lu}",
      (int)index_.testCount, (int)MAX_STORED_TESTS,
      (int)getRemainingCapacity(),
      isStorageFull() ? "true" : "false",
      (unsigned long)index_.nextTestId,
      (unsigned long)LittleFS.totalBytes(),
      (unsigned long)LittleFS.usedBytes());
}

// ═══════════════════════════════════════════════════════════════════
// PRIVATE HELPERS
// ═══════════════════════════════════════════════════════════════════

bool TestStorageService::loadIndex() {
  if (!LittleFS.exists(INDEX_FILE)) {
    return false;
  }
  
  File f = LittleFS.open(INDEX_FILE, "r");
  if (!f) return false;
  
  size_t readBytes = f.read((uint8_t*)&index_, sizeof(TestStorageIndex));
  f.close();
  
  if (readBytes != sizeof(TestStorageIndex) || index_.magic != STORAGE_MAGIC) {
    LOG_WARN(LogCategory::CORE, "TestStorage: Index dosyası bozuk, sıfırlanacak");
    return false;
  }
  
  // Güvenlik: testCount sınırları kontrol et
  if (index_.testCount > MAX_STORED_TESTS) {
    index_.testCount = MAX_STORED_TESTS;
  }
  
  return true;
}

bool TestStorageService::saveIndex() {
  File f = LittleFS.open(INDEX_FILE, "w");
  if (!f) return false;
  
  size_t written = f.write((const uint8_t*)&index_, sizeof(TestStorageIndex));
  f.close();
  
  return (written == sizeof(TestStorageIndex));
}

String TestStorageService::getTestFilePath(uint16_t fileId) {
  char path[32];
  snprintf(path, sizeof(path), "/tests/t_%04u.bin", fileId);
  return String(path);
}

} // namespace GLT
