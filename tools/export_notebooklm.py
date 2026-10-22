import os
import datetime

# Depo kök klasörü (bu script tools/ altında)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Yapılandırma — depo kökündeki proje klasörleri
SOURCE_DIRS = {
    "pc_app": os.path.join(REPO_ROOT, "pc-app"),
    "glt_v3": os.path.join(REPO_ROOT, "firmware", "glt-v3"),
    "master_esp32": os.path.join(REPO_ROOT, "firmware", "master-esp32"),
}

# Çıktı klasörü (depo kökünde, .gitignore ile hariç)
EXPORT_BASE_DIR = os.path.join(REPO_ROOT, "NotebookLM_Export")

# Hariç tutulacak klasörler
EXCLUDE_DIRS = {
    '.git', '.pio', '__pycache__', 'venv', 'node_modules', 'build', 'dist', 
    '.vscode', '.idea', 'bin', 'obj', 'Debug', 'Release', 'ipch',
    'GloveTestSystem_Setup', 'GloveTestSystem_Distribution', 'installer_output',
    'examples', '.agent', '.db_backup', 'reports', 'logs', 'assets',
    'database', 'batches'
}

# Dahil edilecek dosya uzantıları
INCLUDE_EXTS = {
    '.py', '.c', '.cpp', '.h', '.hpp', '.json', '.md', '.txt', '.ini', 
    '.xml', '.conf', '.bat', '.sh', '.yaml', '.yml', '.css', '.js', '.html',
    '.ino', '.csv', '.ps1'
}

# Gizli bilgi içeren dosyalar dışa aktarılmaz
EXCLUDE_FILES = {'secrets.h'}

# Maksimum dosya boyutu (bayt cinsinden, örn: 5MB)
MAX_FILE_SIZE =  500 * 1024 

def is_text_file(filename):
    return any(filename.lower().endswith(ext) for ext in INCLUDE_EXTS)

def write_header(file_handle, source_path):
    file_handle.write(f"\n{'='*50}\n")
    file_handle.write(f"=== DOSYA BAŞLANGICI: {source_path} ===\n")
    file_handle.write(f"{'='*50}\n\n")

def write_footer(file_handle):
    file_handle.write(f"\n\n{'='*50}\n")
    file_handle.write(f"=== DOSYA BİTİŞİ ===\n")
    file_handle.write(f"{'='*50}\n\n")

def process_project(project_name, source_dir, output_dir, file_counter):
    print(f"İşleniyor: {project_name}...")
    
    # Proje için özel çıktı klasörü OLUŞTURMA (Kullanıcı isteği: Hepsi aynı yere)
    project_out_dir = output_dir 
    
    part_num = 1
    # Dosya ismine sayaç ekle: 1_ProjName_Part1.txt
    current_out_path = os.path.join(project_out_dir, f"{file_counter}_{project_name}_Part{part_num}.txt")
    current_file = open(current_out_path, 'w', encoding='utf-8')
    
    file_count = 0
    total_size = 0
    
    for root, dirs, files in os.walk(source_dir):
        # Gereksiz klasörleri atla
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if not is_text_file(file) or file in EXCLUDE_FILES:
                continue
                
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, source_dir)
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                content_len = len(content)
                
                # Dosya boyutunu kontrol et ve gerekirse yeni part'a geç
                if current_file.tell() + content_len > MAX_FILE_SIZE:
                    current_file.close()
                    part_num += 1
                    current_out_path = os.path.join(project_out_dir, f"{project_name}_Part{part_num}.txt")
                    current_file = open(current_out_path, 'w', encoding='utf-8')
                    print(f"  -> Yeni parça oluşturuldu: {os.path.basename(current_out_path)}")
                
                write_header(current_file, rel_path)
                current_file.write(content)
                write_footer(current_file)
                
                current_file.write("\n") # Ayırıcı boşluk
                
                file_count += 1
                total_size += content_len
                
            except Exception as e:
                print(f"Hata ({rel_path}): {e}")
                
    current_file.close()
    print(f"Tamamlandı: {project_name} ({file_count} dosya, {total_size} bayt)")

def main():
    if not os.path.exists(EXPORT_BASE_DIR):
        os.makedirs(EXPORT_BASE_DIR)
        
    print(f"Dışa aktarım klasörü: {EXPORT_BASE_DIR}")
    
    # file_counter_idx = 1 # iptal
    for name, path_dir in SOURCE_DIRS.items():
        if os.path.exists(path_dir):
            process_project(name, path_dir, EXPORT_BASE_DIR, "a")
            # file_counter_idx += 1 # iptal
        else:
            print(f"UYARI: Kaynak klasör bulunamadı -> {path_dir}")

    print(f"\nİşlem bitti! Dosyalarınız burada: {EXPORT_BASE_DIR}")

if __name__ == "__main__":
    main()
