from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"
DEFAULT_HTTP_TIMEOUT_SECONDS = 10
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | pid=%(process)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 5


def resolve_log_level(default: str = DEFAULT_LOG_LEVEL) -> int:
    level_name = os.getenv("INCOME33_LOG_LEVEL", default).strip().upper()
    return getattr(logging, level_name, logging.INFO)


def resolve_log_dir(default: str = DEFAULT_LOG_DIR) -> Path:
    return Path(os.getenv("INCOME33_LOG_DIR", default)).expanduser()


def resolve_http_timeout_seconds(default: int = DEFAULT_HTTP_TIMEOUT_SECONDS) -> int:
    raw = os.getenv("INCOME33_HTTP_TIMEOUT_SECONDS")
    if raw is None or raw.strip() == "":
        return default
    try:
        timeout = int(raw)
    except ValueError:
        return default
    if timeout <= 0:
        return default
    return timeout


def _close_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass


def setup_component_logger(
    logger_name: str,
    log_filename: str,
    *,
    force_reconfigure: bool = False,
) -> logging.Logger:
    """Configure a component logger with console + rotating file handlers.

    The configuration is idempotent by default and can be forced in tests.
    """

    logger = logging.getLogger(logger_name)
    if getattr(logger, "_income33_configured", False) and not force_reconfigure:
        return logger

    if force_reconfigure:
        _close_handlers(logger)
        logger.handlers.clear()

    level = resolve_log_level()
    log_dir = resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / log_filename,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger._income33_configured = True  # type: ignore[attr-defined]

    return logger
