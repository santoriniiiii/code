"""Log técnico en archivo (separado del historial de eventos)."""

from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class _TzFormatter(logging.Formatter):
    def __init__(self, tz: ZoneInfo):
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        self.tz = tz

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        return datetime.fromtimestamp(record.created, self.tz).isoformat(timespec="milliseconds")


def setup_logging(log_path: Path, level: str, tz: ZoneInfo) -> logging.Handler:
    """Configura el log rotativo (5 archivos de 2 MB). Lanza OSError si no se puede crear."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(_TzFormatter(tz))
    root = logging.getLogger("textmonitor")
    root.setLevel(getattr(logging, level))
    root.addHandler(handler)
    root.propagate = False
    return handler
