from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import Settings

LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s | "
    "pid=%(process)d | thread=%(threadName)s | %(message)s"
)
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
UPLOADER_LOGGERS = (
    "app.services.upload_worker",
    "app.services.ingest_client",
)
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_configuration_lock = threading.RLock()
_managed_handlers: list[logging.Handler] = []


def _build_file_handler(
    path: Path,
    *,
    level: int,
    max_bytes: int,
    backup_count: int,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=False,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _detach_handlers(handlers: list[logging.Handler]) -> None:
    if not handlers:
        return
    managed = set(handlers)
    for logger_name in (None, *UPLOADER_LOGGERS, *UVICORN_LOGGERS):
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            if handler in managed:
                logger.removeHandler(handler)


def _replace_named_logger_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)


def configure_logging(config: Settings) -> tuple[Path, Path]:
    """Configure console and persistent logs, failing if files cannot be opened."""
    global _managed_handlers

    log_dir = Path(config.log_dir).expanduser().resolve()
    lwcam_path = log_dir / "lwcam.log"
    uploader_path = log_dir / "uploader.log"
    level = getattr(logging, config.log_level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    new_handlers: list[logging.Handler] = []

    try:
        log_dir.mkdir(parents=True, exist_ok=True)

        console = logging.StreamHandler(sys.stderr)
        console.setLevel(level)
        console.setFormatter(formatter)
        new_handlers.append(console)

        lwcam_file = _build_file_handler(
            lwcam_path,
            level=level,
            max_bytes=config.log_max_bytes,
            backup_count=config.log_backup_count,
            formatter=formatter,
        )
        new_handlers.append(lwcam_file)

        uploader_file = _build_file_handler(
            uploader_path,
            level=level,
            max_bytes=config.log_max_bytes,
            backup_count=config.log_backup_count,
            formatter=formatter,
        )
        new_handlers.append(uploader_file)
    except Exception:
        for handler in new_handlers:
            handler.close()
        raise

    with _configuration_lock:
        previous_handlers = _managed_handlers
        _detach_handlers(previous_handlers)

        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(console)
        root.addHandler(lwcam_file)

        for logger_name in UPLOADER_LOGGERS:
            logger = logging.getLogger(logger_name)
            _replace_named_logger_handlers(logger)
            logger.setLevel(level)
            logger.propagate = False
            logger.addHandler(console)
            logger.addHandler(uploader_file)

        uvicorn = logging.getLogger("uvicorn")
        _replace_named_logger_handlers(uvicorn)
        uvicorn.setLevel(level)
        uvicorn.propagate = False
        uvicorn.addHandler(console)
        uvicorn.addHandler(lwcam_file)

        uvicorn_error = logging.getLogger("uvicorn.error")
        _replace_named_logger_handlers(uvicorn_error)
        uvicorn_error.setLevel(level)
        uvicorn_error.propagate = True

        uvicorn_access = logging.getLogger("uvicorn.access")
        _replace_named_logger_handlers(uvicorn_access)
        uvicorn_access.setLevel(level)
        uvicorn_access.propagate = False
        uvicorn_access.addHandler(console)
        uvicorn_access.addHandler(lwcam_file)

        _managed_handlers = new_handlers
        for handler in previous_handlers:
            handler.close()

    logging.getLogger(__name__).info(
        "Persistent logging initialized: lwcam=%s uploader=%s max_bytes=%s backups=%s",
        lwcam_path,
        uploader_path,
        config.log_max_bytes,
        config.log_backup_count,
    )
    return lwcam_path, uploader_path


__all__ = ["configure_logging"]
