"""Structured logging: one JSON object per line on standard output (10A.8).

Levels: 2xx, 3xx and 4xx are INFO. 401 and 429 are WARNING. 5xx are ERROR and
include the traceback. No API key, X-API-Key or Authorization header is logged.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from stand_allocation import config

_EXTRA_FIELDS = (
    "run_id",
    "request_id",
    "route",
    "method",
    "path",
    "status",
    "status_class",
    "client_ip",
    "duration_ms",
    "rate_limited",
    "key_fingerprint",
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload)


def setup_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
