"""
Centralized Application Logger
Writes all errors/warnings to a rotating log file (app.log).
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3

_initialized = False


def _get_log_path() -> str:
    """Determine log file path using the same data dir as storage_config."""
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        data_dir = os.path.join(base, "Ultra GITS")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "app.log")
    # Dev mode — log next to src/
    return os.path.join(os.path.dirname(__file__), "..", "..", "app.log")


def _setup_root_logger():
    """Configure root logger once with file + console handlers."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    root = logging.getLogger("glt")
    root.setLevel(logging.DEBUG)

    # File handler (rotating)
    try:
        log_path = _get_log_path()
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        fh = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(fh)
    except Exception:
        pass  # If file handler fails, at least console works

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'glt' namespace."""
    _setup_root_logger()
    return logging.getLogger(f"glt.{name}")
