"""
scripts/lib/log_setup.py
Shared logging setup for OHLCV ETL scripts.

Writes to BOTH:
  1. stdout (for manual runs / systemd / docker logs)
  2. /var/log/datapai/<script_name>.log  (persistent rotating file)
     Falls back to  scripts/logs/<script_name>.log  if /var/log/datapai
     is not writable (e.g. local dev on macOS).

Log rotation: 10 MB max, last 5 files kept.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR_PRIMARY = Path("/var/log/datapai")
_LOG_DIR_FALLBACK = Path(__file__).resolve().parent.parent / "logs"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5
_FMT = "%(asctime)s  %(levelname)-8s [%(name)s]  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _resolve_log_dir() -> Path:
    env_dir = os.environ.get("DATAPAI_LOG_DIR")
    if env_dir:
        d = Path(env_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if _LOG_DIR_PRIMARY.exists() and os.access(_LOG_DIR_PRIMARY, os.W_OK):
        return _LOG_DIR_PRIMARY
    _LOG_DIR_FALLBACK.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR_FALLBACK


def get_log_path(name: str) -> Path:
    return _resolve_log_dir() / f"{name}.log"


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    fmt = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # stdout handler
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # rotating file handler
    try:
        log_path = get_log_path(name)
        fh = RotatingFileHandler(str(log_path), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.info("Logging initialised → %s", log_path)
    except (OSError, PermissionError) as e:
        logger.warning("Could not create file handler: %s", e)

    return logger
