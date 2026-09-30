"""Structured, privacy-safe logging for the watch service."""

import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOGGERS: dict[Path, logging.Logger] = {}


class _JsonWatchFormatter(logging.Formatter):
    """Format explicitly supplied watch event payloads as JSON Lines."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the structured payload attached to a watch event record.

        :param record: Log record created by :func:`log_watch_event`.
        :type record: logging.LogRecord
        :return: A compact JSON object suitable for one JSONL line.
        :rtype: str
        """
        payload = getattr(record, "watch_payload", {})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class _HumanWatchFormatter(logging.Formatter):
    """Format watch events as concise messages for stderr."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a readable summary of the structured watch event.

        :param record: Log record created by :func:`log_watch_event`.
        :type record: logging.LogRecord
        :return: A readable stderr message.
        :rtype: str
        """
        payload = getattr(record, "watch_payload", {})
        event = payload.get("event", record.getMessage())
        details = [
            f"{key}={value}"
            for key, value in payload.items()
            if key not in {"event", "message", "schema_version"}
        ]
        suffix = f" {' '.join(details)}" if details else ""
        return f"{record.levelname} {event}{suffix}"


def get_watch_log_path(store_path: Path) -> Path:
    """Derive the canonical hidden log path for a watch-rule store.

    :param store_path: Path to the persisted watch-rule store.
    :type store_path: pathlib.Path
    :return: Resolved hidden log file beside the resolved store path.
    :rtype: pathlib.Path
    """
    resolved_store_path = store_path.resolve()
    return resolved_store_path.with_name(f".{resolved_store_path.name}.log")


def setup_watch_logging(log_path: Path, verbosity: int = 1) -> logging.Logger:
    """Configure one stderr and JSONL logger for a canonical log path.

    :param log_path: Destination for rotating structured JSONL events.
    :type log_path: pathlib.Path
    :param verbosity: Console verbosity where 0 is WARNING, 1 is INFO, and 2 is DEBUG.
    :type verbosity: int
    :return: The configured logger for the canonical log path.
    :rtype: logging.Logger
    """
    canonical_log_path = log_path.resolve()
    existing_logger = _LOGGERS.get(canonical_log_path)
    if existing_logger is not None:
        return existing_logger

    # Use a path-derived name so independent stores cannot share handlers.
    logger_name = hashlib.sha256(str(canonical_log_path).encode("utf-8")).hexdigest()
    logger = logging.getLogger(f"autometa.watch.{logger_name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    canonical_log_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep machine-readable history separate from human-facing stderr output.
    file_handler = RotatingFileHandler(
        canonical_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(_JsonWatchFormatter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)
    )
    console_handler.setFormatter(_HumanWatchFormatter())
    logger.addHandler(console_handler)

    _LOGGERS[canonical_log_path] = logger
    return logger


def log_watch_event(
    logger: logging.Logger, event: str, level: int, **fields: Any
) -> None:
    """Emit one structured watch event without exposing arbitrary log metadata.

    :param logger: Logger returned by :func:`setup_watch_logging`.
    :type logger: logging.Logger
    :param event: Stable event identifier recorded in the JSON payload and message.
    :type event: str
    :param level: Standard-library logging level for the event.
    :type level: int
    :param fields: Explicit event fields to include in the structured payload.
    :type fields: typing.Any
    :return: ``None``.
    :rtype: None
    """
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event": event,
        "message": event,
    }
    payload.update(_serialize_fields(fields))
    logger.log(level, event, extra={"watch_payload": payload})


def _serialize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Convert explicit fields into deterministic JSON-compatible values.

    :param fields: Event fields supplied to :func:`log_watch_event`.
    :type fields: dict[str, typing.Any]
    :return: Converted event fields.
    :rtype: dict[str, typing.Any]
    """
    serialized = {key: _serialize_value(value) for key, value in fields.items()}
    if "rule_ids" in serialized:
        serialized["rule_ids"] = sorted(serialized["rule_ids"])
    return serialized


def _serialize_value(value: Any) -> Any:
    """Convert supported structured values into stable JSON-compatible forms.

    :param value: Explicit watch event field value.
    :type value: typing.Any
    :return: JSON-compatible representation of ``value``.
    :rtype: typing.Any
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, set):
        converted = [_serialize_value(item) for item in value]
        return sorted(
            converted,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value
