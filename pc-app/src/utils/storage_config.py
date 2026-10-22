"""
Storage Configuration — bootstrap config file for storage base path.
Uses a JSON file. For frozen (PyInstaller) builds, config and data live
in %LOCALAPPDATA%/Ultra GITS so the app works WITHOUT admin privileges
even when installed in C:\\Program Files.
"""

import json
import os
import shutil
import sys

# ── Writable data directory ──────────────────────────────────────────
_APP_NAME = "Ultra GITS"


def _get_writable_data_dir() -> str:
    """
    Return a guaranteed-writable data directory for the application.
    - Frozen exe  → %LOCALAPPDATA%/Ultra GITS  (always writable)
    - Dev mode    → "" (empty → CWD-relative, backward compatible)
    """
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        data_dir = os.path.join(base, _APP_NAME)
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return ""


# ── Config file location ─────────────────────────────────────────────
_DATA_DIR = _get_writable_data_dir()

if _DATA_DIR:
    # Frozen exe → config in %LOCALAPPDATA%/Ultra GITS/
    _CONFIG_DIR = _DATA_DIR
else:
    # Dev mode → next to src/ (parent of this file's parent)
    _CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CONFIG_FILE = os.path.join(_CONFIG_DIR, "storage_config.json")

# Default: empty string → use application directory (backward compatible)
_DEFAULTS = {
    "storage_base_path": ""
}


def _read_config() -> dict:
    """Read the JSON config file, returning defaults on failure."""
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
    except Exception as e:
        print(f"[StorageConfig] Config read error: {e}")
    return dict(_DEFAULTS)


def _write_config(data: dict):
    """Write config dict to JSON file."""
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[StorageConfig] Config write error: {e}")


def get_storage_base_path() -> str:
    """
    Return the storage base path.
    Empty string means 'use application directory' (backward compatible).
    """
    cfg = _read_config()
    return cfg.get("storage_base_path", "")


def set_storage_base_path(path: str):
    """Save a new storage base path to config."""
    cfg = _read_config()
    cfg["storage_base_path"] = path
    _write_config(cfg)


def get_database_path(base: str = None) -> str:
    """Return full path to glove_test.db given a base path."""
    if base is None:
        base = get_storage_base_path()
    if not base:
        base = _DATA_DIR  # frozen → %LOCALAPPDATA%/Ultra GITS, dev → ""
    if not base:
        return "database/glove_test.db"
    return os.path.join(base, "database", "glove_test.db")


def get_reports_path(base: str = None) -> str:
    """Return the reports output directory."""
    if base is None:
        base = get_storage_base_path()
    if not base:
        base = _DATA_DIR
    if not base:
        return "reports"
    return os.path.join(base, "reports")


def get_batches_path(base: str = None) -> str:
    """Return the batches output directory."""
    if base is None:
        base = get_storage_base_path()
    if not base:
        base = _DATA_DIR
    if not base:
        return "batches"
    return os.path.join(base, "batches")


# ── Database backup ──────────────────────────────────────────────────
_BACKUP_DIR_NAME = ".db_backup"


def _get_backup_dir() -> str:
    """Return hidden backup directory path inside _internal (frozen) or src (dev)."""
    if getattr(sys, 'frozen', False):
        # _internal klasörü: exe'nin yanındaki PyInstaller runtime dizini
        internal = os.path.join(os.path.dirname(sys.executable), "_internal")
        return os.path.join(internal, _BACKUP_DIR_NAME)
    # Dev mode: src klasörünün yanı
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(src_dir, _BACKUP_DIR_NAME)


def backup_database(db_path: str) -> bool:
    """Ana veritabanını gizli yedek klasöre kopyalar. Başarılıysa True döner."""
    if not os.path.isfile(db_path):
        return False
    try:
        backup_dir = _get_backup_dir()
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, "glove_test.db")
        shutil.copy2(db_path, backup_file)
        return True
    except Exception as e:
        print(f"[StorageConfig] DB backup error: {e}")
        return False


def restore_database_from_backup(db_path: str) -> bool:
    """Ana DB yoksa yedekten geri yükler. Başarılıysa True döner."""
    if os.path.isfile(db_path):
        return False  # Ana DB zaten var, geri yükleme gereksiz
    backup_file = os.path.join(_get_backup_dir(), "glove_test.db")
    if not os.path.isfile(backup_file):
        return False  # Yedek de yok
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        shutil.copy2(backup_file, db_path)
        print(f"[StorageConfig] DB restored from backup: {backup_file}")
        return True
    except Exception as e:
        print(f"[StorageConfig] DB restore error: {e}")
        return False
