"""Behavior tests for querying structured watch-service logs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autometa.log_query import (
    parse_since,
    query_watch_logs,
    stream_watch_logs,
    summarize_watch_logs,
)


def _write_log(path: Path, records: list[dict[str, object]]) -> None:
    """Write JSONL records for one log-query test fixture.

    :param path: Destination JSONL file.
    :type path: pathlib.Path
    :param records: Structured records to write.
    :type records: list[dict[str, object]]
    :return: None.
    :rtype: None
    """
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def test_query_watch_logs_reads_rotations_oldest_first_and_filters(
    tmp_path: Path,
) -> None:
    """Queries merge rotated logs and filter by event, path, rule, and level.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    """
    log_path = tmp_path / ".watchers.yaml.log"
    _write_log(
        log_path.with_name(f"{log_path.name}.1"),
        [
            {
                "event": "watch.path_queued",
                "level": "INFO",
                "path": "/music/old.mp3",
                "rule_ids": ["old-rule"],
                "timestamp": "2026-09-30T00:00:00Z",
            }
        ],
    )
    _write_log(
        log_path,
        [
            {
                "event": "watch.metadata_updated",
                "level": "INFO",
                "path": "/music/new.mp3",
                "rule_ids": ["rule-1"],
                "timestamp": "2026-09-30T00:01:00Z",
            },
            {
                "event": "watch.reconciliation_failed",
                "level": "ERROR",
                "path": "/music/new.mp3",
                "rule_ids": ["rule-1"],
                "timestamp": "2026-09-30T00:02:00Z",
            },
        ],
    )

    records = query_watch_logs(
        log_path,
        event="watch.reconciliation_failed",
        path="new.mp3",
        rule_id="rule-1",
        level="ERROR",
    )

    assert records == [
        {
            "event": "watch.reconciliation_failed",
            "level": "ERROR",
            "path": "/music/new.mp3",
            "rule_ids": ["rule-1"],
            "timestamp": "2026-09-30T00:02:00Z",
        }
    ]


def test_query_watch_logs_tail_applies_after_filters(tmp_path: Path) -> None:
    """Tail returns the newest matching records across the log history.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    """
    log_path = tmp_path / ".watchers.yaml.log"
    _write_log(
        log_path,
        [
            {
                "event": "watch.metadata_unchanged",
                "level": "INFO",
                "timestamp": f"2026-09-30T00:0{index}:00Z",
            }
            for index in range(3)
        ],
    )

    records = query_watch_logs(log_path, tail=2)

    assert [record["timestamp"] for record in records] == [
        "2026-09-30T00:01:00Z",
        "2026-09-30T00:02:00Z",
    ]
    assert query_watch_logs(log_path, tail=0) == []


def test_follow_snapshot_splits_history_from_new_records_without_duplicates(
    tmp_path: Path,
) -> None:
    """A shared boundary prevents a follow handoff from skipping or replaying records.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    """
    from autometa.log_query import snapshot_watch_log

    log_path = tmp_path / ".watchers.yaml.log"
    old = {"event": "old"}
    new = {"event": "new"}
    _write_log(log_path, [old])
    snapshot = snapshot_watch_log(log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(new) + "\n")

    assert query_watch_logs(log_path, active_limit=snapshot.offset) == [old]
    assert next(stream_watch_logs(log_path, poll_interval=0, snapshot=snapshot)) == new


def test_stream_watch_logs_resets_after_atomic_rotation(tmp_path: Path) -> None:
    """Following logs reads a replacement file even when it exceeds the old size.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    """
    log_path = tmp_path / ".watchers.yaml.log"
    _write_log(log_path, [{"event": "old", "padding": "x" * 200}])
    stream = stream_watch_logs(log_path, poll_interval=0)
    replacement = tmp_path / "replacement.log"
    expected = {"event": "new", "padding": "y" * 300}
    _write_log(replacement, [expected])
    replacement.replace(log_path)

    assert next(stream) == expected


def test_parse_since_and_summary_count_events_levels_and_actions() -> None:
    """Relative durations parse against UTC and summaries aggregate record fields."""
    now = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)

    assert parse_since("90m", now=now) == now - timedelta(minutes=90)
    assert summarize_watch_logs(
        [
            {"event": "watch.metadata_updated", "level": "INFO"},
            {"event": "watch.metadata_updated", "level": "INFO"},
            {"event": "watch.reconciliation_failed", "level": "ERROR"},
        ]
    ) == {
        "events": {
            "watch.metadata_updated": 2,
            "watch.reconciliation_failed": 1,
        },
        "levels": {"ERROR": 1, "INFO": 2},
        "total": 3,
    }
