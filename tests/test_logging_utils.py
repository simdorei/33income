import logging
from logging.handlers import RotatingFileHandler

from income33.logging_utils import setup_component_logger


def test_setup_component_logger_creates_rotating_file_handler(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("INCOME33_LOG_DIR", str(log_dir))
    monkeypatch.setenv("INCOME33_LOG_LEVEL", "DEBUG")

    logger = setup_component_logger(
        "income33.test.logging",
        "test.log",
        force_reconfigure=True,
    )

    assert logger.level == logging.DEBUG

    rotating_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1

    file_handler = rotating_handlers[0]
    assert file_handler.maxBytes == 5 * 1024 * 1024
    assert file_handler.backupCount == 5

    logger.debug("test message")
    for handler in logger.handlers:
        handler.flush()

    assert log_dir.exists()
    log_file = log_dir / "test.log"
    assert log_file.exists()
    assert "test message" in log_file.read_text(encoding="utf-8")


def test_setup_component_logger_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("INCOME33_LOG_LEVEL", "INFO")

    logger = setup_component_logger(
        "income33.test.idempotent",
        "idempotent.log",
        force_reconfigure=True,
    )
    first_count = len(logger.handlers)

    logger = setup_component_logger("income33.test.idempotent", "idempotent.log")
    second_count = len(logger.handlers)

    assert first_count == second_count
