"""JSONL logging for the server half of the log contract (docs/BLUEPRINT.md, section 6.3).

One JSON object per line with `ts`, `source`, `level`, `msg` plus any `extra=` fields. Secrets named
in REDACT_ENV, and Google iCal private tokens, are masked inside the formatter, so tracebacks and
extra fields are covered and not only the message. Output is ASCII-only JSON so a legacy Windows
console code page can never break logging. Records written while a request is being handled pick up
its request ID automatically.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from app.core.context import request_id_var

MASK = "***"
MIN_SECRET_LENGTH = 8  # shorter values would also mask ordinary words

_ICAL_TOKEN = re.compile(r"private-[0-9a-fA-F]{16,}")
_LEVELS = {"DEBUG": "debug", "INFO": "info", "WARNING": "warning", "ERROR": "error", "CRITICAL": "error"}
# Attributes every LogRecord carries. Anything else arrived through `extra=` and becomes a field.
# `color_message` is uvicorn's ANSI-coloured duplicate of the message.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "color_message",
}


_registered: set[str] = set()


def register_secret(value: str | None) -> None:
    """Masks `value` in every log line from now on. Settings call this for secrets that came from the repo's .env
    file, which never reaches os.environ and so would otherwise be invisible to the redactor."""
    if value and len(value) >= MIN_SECRET_LENGTH:
        _registered.add(value)


class Redactor:
    """Masks the values of the env vars named in REDACT_ENV, secrets registered by the settings, and iCal private tokens."""

    def __init__(self, env_names: str | None = None) -> None:
        self._env_names = env_names

    def _secrets(self) -> list[str]:
        names = self._env_names if self._env_names is not None else os.environ.get("REDACT_ENV", "GCAL_ICAL_URL")
        values = {os.environ.get(name.strip(), "") for name in names.split(",") if name.strip()} | _registered
        return sorted((value for value in values if len(value) >= MIN_SECRET_LENGTH), key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self._secrets():
            value = value.replace(secret, MASK)
        return _ICAL_TOKEN.sub(MASK, value)

    def deep(self, value: Any, depth: int = 0) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if depth < 4 and isinstance(value, dict):
            return {key: self.deep(item, depth + 1) for key, item in value.items()}
        if depth < 4 and isinstance(value, (list, tuple)):
            return [self.deep(item, depth + 1) for item in value]
        return value


class JsonFormatter(logging.Formatter):
    def __init__(self, source: str = "server", redact_env: str | None = None) -> None:
        super().__init__()
        self._source = source
        self._redactor = Redactor(redact_env)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds")
        entry: dict[str, Any] = {
            "ts": timestamp.replace("+00:00", "Z"),
            "source": self._source,
            "level": _LEVELS.get(record.levelname, "info"),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if "request_id" not in entry:
            request_id = request_id_var.get()
            if request_id:
                entry["request_id"] = request_id
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(self._redactor.deep(entry), default=str)
