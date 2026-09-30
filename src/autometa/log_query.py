"""Read and filter structured JSONL watch-service logs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from typing import Any

_DURATION_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[smhdw])$")


@dataclass(frozen=True)
class LogSnapshot:
    """Active-log identity and byte offset captured for a follow handoff."""

    identity: tuple[int, int] | None
    offset: int


def snapshot_watch_log(log_path: Path) -> LogSnapshot:
    """Capture the current active-log byte boundary for a race-free handoff.

    :param log_path: Canonical active watch-log path.
    :type log_path: pathlib.Path
    :return: Active file identity and the byte offset observed at capture time.
    :rtype: LogSnapshot
    """
    try:
        stat = log_path.stat()
    except OSError:
        return LogSnapshot(None, 0)
    return LogSnapshot((stat.st_dev, stat.st_ino), stat.st_size)


def iter_watch_log_paths(log_path: Path) -> list[Path]:
    """Return existing rotated logs followed by the active JSONL log.

    :param log_path: Canonical active watch-log path.
    :type log_path: pathlib.Path
    :return: Existing paths ordered from oldest to newest.
    :rtype: list[pathlib.Path]
    """
    rotated: list[tuple[int, Path]] = []
    prefix = f"{log_path.name}."
    for candidate in log_path.parent.glob(f"{log_path.name}.*"):
        suffix = candidate.name.removeprefix(prefix)
        if suffix.isdigit():
            rotated.append((int(suffix), candidate))
    return [path for _, path in sorted(rotated, reverse=True)] + (
        [log_path] if log_path.is_file() else []
    )


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """Convert a compact relative duration into a UTC threshold.

    :param value: Positive integer followed by ``s``, ``m``, ``h``, ``d``, or ``w``.
    :type value: str
    :param now: Reference UTC time, primarily injectable for tests.
    :type now: datetime.datetime | None
    :return: UTC instant at the requested duration before ``now``.
    :rtype: datetime.datetime
    :raises ValueError: If ``value`` is not a supported positive duration.
    """
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("--since must be a positive duration such as 30m, 2h, or 7d.")
    amount = int(match["value"])
    if amount < 1:
        raise ValueError("--since must be a positive duration such as 30m, 2h, or 7d.")
    unit = match["unit"]
    units = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }
    return (now or datetime.now(timezone.utc)) - units[unit]


def query_watch_logs(
    log_path: Path,
    *,
    tail: int | None = None,
    event: str | None = None,
    path: str | None = None,
    rule_id: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    active_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read rotated JSONL records and apply explicit filters.

    Malformed partial lines are skipped so a concurrent writer cannot make log
    inspection fail. Older records without timestamps are retained unless a
    ``since`` threshold requires timestamp comparison.

    :param log_path: Canonical active watch-log path.
    :type log_path: pathlib.Path
    :param tail: Maximum number of newest matching records to return.
    :type tail: int | None
    :param event: Exact event identifier filter.
    :type event: str | None
    :param path: Case-insensitive substring filter for the recorded file path.
    :type path: str | None
    :param rule_id: Exact matching rule ID filter.
    :type rule_id: str | None
    :param level: Exact uppercase log-level filter.
    :type level: str | None
    :param since: Inclusive UTC timestamp threshold.
    :type since: datetime.datetime | None
    :param active_limit: Maximum active-log bytes to include, for follow handoff.
    :type active_limit: int | None
    :return: Matching records in chronological order.
    :rtype: list[dict[str, typing.Any]]
    :raises ValueError: If ``tail`` is negative.
    """
    if tail is not None and tail < 0:
        raise ValueError("--tail must be zero or a positive integer.")
    records = [
        record
        for file_path in iter_watch_log_paths(log_path)
        for record in _read_jsonl(
            file_path, limit=active_limit if file_path == log_path else None
        )
        if _matches_record(
            record,
            event=event,
            path=path,
            rule_id=rule_id,
            level=level,
            since=since,
        )
    ]
    if tail == 0:
        return []
    return records[-tail:] if tail is not None else records


def stream_watch_logs(
    log_path: Path,
    *,
    poll_interval: float = 0.2,
    event: str | None = None,
    path: str | None = None,
    rule_id: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    snapshot: LogSnapshot | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield complete records appended to the active log after invocation.

    :param log_path: Canonical active watch-log path.
    :type log_path: pathlib.Path
    :param poll_interval: Seconds to wait between file-size checks.
    :type poll_interval: float
    :param event: Exact event identifier filter.
    :type event: str | None
    :param path: Case-insensitive path substring filter.
    :type path: str | None
    :param rule_id: Exact rule-ID filter.
    :type rule_id: str | None
    :param level: Exact severity filter.
    :type level: str | None
    :param since: Inclusive UTC timestamp threshold.
    :type since: datetime.datetime | None
    :return: Iterator of newly appended matching JSON records.
    :rtype: collections.abc.Iterator[dict[str, typing.Any]]
    """
    snapshot = snapshot or snapshot_watch_log(log_path)
    return _stream_watch_log_records(
        log_path,
        offset=snapshot.offset,
        identity=snapshot.identity,
        poll_interval=poll_interval,
        event=event,
        path=path,
        rule_id=rule_id,
        level=level,
        since=since,
    )


def _stream_watch_log_records(
    log_path: Path,
    *,
    offset: int,
    identity: tuple[int, int] | None,
    poll_interval: float,
    event: str | None,
    path: str | None,
    rule_id: str | None,
    level: str | None,
    since: datetime | None,
) -> Iterator[dict[str, Any]]:
    """Yield appended records while tracking rotation and incomplete writes.

    :param log_path: Canonical active watch-log path.
    :type log_path: pathlib.Path
    :param offset: Byte position after the last complete line.
    :type offset: int
    :param identity: Device/inode identity for the last active file.
    :type identity: tuple[int, int] | None
    :param poll_interval: Seconds to wait between file-size checks.
    :type poll_interval: float
    :param event: Exact event identifier filter.
    :type event: str | None
    :param path: Case-insensitive path substring filter.
    :type path: str | None
    :param rule_id: Exact rule-ID filter.
    :type rule_id: str | None
    :param level: Exact severity filter.
    :type level: str | None
    :param since: Inclusive UTC timestamp threshold.
    :type since: datetime.datetime | None
    :return: Iterator of newly appended matching JSON records.
    :rtype: collections.abc.Iterator[dict[str, typing.Any]]
    """
    while True:
        try:
            stat = log_path.stat()
        except OSError:
            identity = None
            offset = 0
        else:
            current_identity = (stat.st_dev, stat.st_ino)
            if current_identity != identity or stat.st_size < offset:
                identity = current_identity
                offset = 0
            if stat.st_size > offset:
                with log_path.open(encoding="utf-8") as handle:
                    handle.seek(offset)
                    while line := handle.readline():
                        if not line.endswith("\n"):
                            break
                        offset = handle.tell()
                        record = _parse_line(line)
                        if record is not None and _matches_record(
                            record,
                            event=event,
                            path=path,
                            rule_id=rule_id,
                            level=level,
                            since=since,
                        ):
                            yield record
        time.sleep(poll_interval)


def summarize_watch_logs(records: list[dict[str, Any]]) -> dict[str, object]:
    """Count matching records by event and severity.

    :param records: Records returned by :func:`query_watch_logs`.
    :type records: list[dict[str, typing.Any]]
    :return: Count mapping suitable for JSON or human-readable output.
    :rtype: dict[str, object]
    """
    return {
        "events": dict(
            sorted(
                Counter(
                    str(record.get("event", "unknown")) for record in records
                ).items()
            )
        ),
        "levels": dict(
            sorted(
                Counter(
                    str(record.get("level", "UNKNOWN")) for record in records
                ).items()
            )
        ),
        "total": len(records),
    }


def format_watch_log_record(record: dict[str, Any]) -> str:
    """Render one structured record as a concise line for terminal output.

    :param record: JSONL record to display.
    :type record: dict[str, typing.Any]
    :return: One human-readable record line.
    :rtype: str
    """
    fields = [
        f"{key}={record[key]}"
        for key in ("path", "rule_ids", "changed_tags", "reason", "stage")
        if key in record
    ]
    suffix = f" {' '.join(fields)}" if fields else ""
    return (
        " ".join(
            [
                str(record.get("timestamp", "-")),
                str(record.get("level", "UNKNOWN")),
                str(record.get("event", "unknown")),
            ]
        )
        + suffix
    )


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read valid object records from one JSONL file.

    :param path: Existing JSONL file.
    :type path: pathlib.Path
    :param limit: Maximum byte offset to read, or ``None`` for the whole file.
    :type limit: int | None
    :return: Parsed object records.
    :rtype: list[dict[str, typing.Any]]
    """
    try:
        with path.open(encoding="utf-8") as handle:
            records: list[dict[str, Any]] = []
            while handle.tell() < limit if limit is not None else True:
                line = handle.readline()
                if not line:
                    break
                if limit is not None and handle.tell() > limit:
                    break
                record = _parse_line(line)
                if record is not None:
                    records.append(record)
            return records
    except OSError:
        return []


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse one JSONL object while tolerating partial/corrupt records.

    :param line: Candidate JSONL line.
    :type line: str
    :return: Object record or ``None`` when the line is unusable.
    :rtype: dict[str, typing.Any] | None
    """
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _matches_record(
    record: dict[str, Any],
    *,
    event: str | None,
    path: str | None,
    rule_id: str | None,
    level: str | None,
    since: datetime | None,
) -> bool:
    """Return whether a record meets every requested filter.

    :param record: Candidate parsed JSONL record.
    :type record: dict[str, typing.Any]
    :param event: Exact event filter.
    :type event: str | None
    :param path: Case-insensitive path substring filter.
    :type path: str | None
    :param rule_id: Exact rule-ID filter.
    :type rule_id: str | None
    :param level: Exact severity filter.
    :type level: str | None
    :param since: Inclusive UTC timestamp threshold.
    :type since: datetime.datetime | None
    :return: Whether the record matches all filters.
    :rtype: bool
    """
    if event is not None and record.get("event") != event:
        return False
    if (
        path is not None
        and path.casefold() not in str(record.get("path", "")).casefold()
    ):
        return False
    if rule_id is not None and rule_id not in record.get("rule_ids", []):
        return False
    if level is not None and record.get("level") != level:
        return False
    if since is not None:
        timestamp = _parse_timestamp(record.get("timestamp"))
        if timestamp is None or timestamp < since:
            return False
    return True


def _parse_timestamp(value: object) -> datetime | None:
    """Parse one ISO-8601 UTC timestamp value.

    :param value: Candidate serialized timestamp.
    :type value: object
    :return: Timezone-aware instant or ``None`` for invalid/missing input.
    :rtype: datetime.datetime | None
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
