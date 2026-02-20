from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from traceback import format_exception


_MAX_ENTRIES = 5000
_BUFFER: deque[dict] = deque(maxlen=_MAX_ENTRIES)
_LOCK = Lock()
_HANDLER: "InMemoryLogHandler | None" = None
_LOGGER_NAMES = ("onnx_host", "uvicorn.error", "uvicorn.access")


def _subsystem_from_logger(logger_name: str) -> str:
    if not logger_name:
        return "root"

    if logger_name == "uvicorn.access":
        return "http.access"
    if logger_name.startswith("uvicorn."):
        return "server"

    parts = logger_name.split(".")
    if parts[0] == "onnx_host":
        if len(parts) == 1:
            return "host"
        if parts[1] == "api":
            if len(parts) > 2:
                return f"api.{parts[2]}"
            return "api"
        return parts[1]

    return parts[0]


class InMemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        logger_name = record.name
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": logger_name,
            "subsystem": _subsystem_from_logger(logger_name),
            "message": record.getMessage(),
        }

        if record.exc_info:
            entry["exception"] = "".join(format_exception(*record.exc_info)).rstrip()

        with _LOCK:
            _BUFFER.append(entry)


def _attach_handler(logger: logging.Logger, handler: logging.Handler) -> None:
    if any(existing is handler for existing in logger.handlers):
        return
    logger.addHandler(handler)


def setup_runtime_logging() -> None:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = InMemoryLogHandler()
        _HANDLER.setLevel(logging.DEBUG)

    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        _attach_handler(logger, _HANDLER)


def clear_logs() -> None:
    with _LOCK:
        _BUFFER.clear()


def get_recent_logs(
    limit: int = 200,
    min_level: str | None = None,
    include_access_logs: bool = False,
) -> list[dict]:
    level_value = None
    if min_level:
        normalized = min_level.upper()
        level_value = logging.getLevelName(normalized)
        if not isinstance(level_value, int):
            level_value = None

    with _LOCK:
        items = list(_BUFFER)

    if not include_access_logs:
        items = [item for item in items if item.get("logger") != "uvicorn.access"]

    if level_value is not None:
        filtered: list[dict] = []
        for item in items:
            item_level = logging.getLevelName(str(item.get("level", "")).upper())
            if isinstance(item_level, int) and item_level >= level_value:
                filtered.append(item)
        items = filtered

    return items[-limit:]
