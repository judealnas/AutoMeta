"""Behavior tests for structured watch-service logging."""

import json
import logging
from pathlib import Path
import sys
from unittest.mock import patch

from autometa.watch_logging import (
    get_watch_log_path,
    log_watch_event,
    setup_watch_logging,
)


def test_get_watch_log_path_resolves_to_a_hidden_sibling(tmp_path: Path) -> None:
    """A store path maps to its deterministic hidden sibling log path."""
    store_path = tmp_path / "nested" / ".." / "watchers.yaml"

    assert get_watch_log_path(store_path) == (tmp_path.resolve() / ".watchers.yaml.log")


def test_log_watch_event_writes_a_private_structured_json_line(tmp_path: Path) -> None:
    """An event writes only its stable schema and explicitly supplied fields."""
    log_path = tmp_path / "watch.log"
    logger = setup_watch_logging(log_path)
    watched_path = tmp_path / "music" / "song.mp3"

    log_watch_event(
        logger,
        "file_processed",
        logging.INFO,
        path=watched_path,
        rule_ids={"rule-z", "rule-a"},
    )

    lines = log_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    record = json.loads(lines[0])

    assert record == {
        "schema_version": 1,
        "event": "file_processed",
        "level": "INFO",
        "message": "file_processed",
        "path": str(watched_path),
        "rule_ids": ["rule-a", "rule-z"],
        "timestamp": record["timestamp"],
    }
    assert record["timestamp"].endswith("Z")
    assert "pathname" not in record


def test_log_watch_event_preserves_required_schema_fields(tmp_path: Path) -> None:
    """Caller fields cannot replace the stable watch-event schema fields."""
    log_path = tmp_path / "reserved-fields.log"
    logger = setup_watch_logging(log_path)
    watched_path = tmp_path / "music" / "song.mp3"

    log_watch_event(
        logger,
        "watch.path_queued",
        logging.INFO,
        schema_version=99,
        message="bad",
        event="bad",
        path=watched_path,
    )

    record = json.loads(log_path.read_text(encoding="utf-8"))

    assert record == {
        "schema_version": 1,
        "event": "watch.path_queued",
        "level": "INFO",
        "message": "watch.path_queued",
        "path": str(watched_path),
        "timestamp": record["timestamp"],
    }


def test_log_watch_event_converts_paths_tuples_and_sets_deterministically(
    tmp_path: Path,
) -> None:
    """Structured values are converted into stable JSON-compatible data."""
    log_path = tmp_path / "converted.log"
    logger = setup_watch_logging(log_path)

    log_watch_event(
        logger,
        "batch_processed",
        logging.INFO,
        locations=(tmp_path / "b", tmp_path / "a"),
        labels={"zeta", "alpha"},
        nested={"paths": {tmp_path / "two", tmp_path / "one"}},
    )

    entry = json.loads(log_path.read_text(encoding="utf-8"))

    assert entry["locations"] == [str(tmp_path / "b"), str(tmp_path / "a")]
    assert entry["labels"] == ["alpha", "zeta"]
    assert entry["nested"] == {"paths": [str(tmp_path / "one"), str(tmp_path / "two")]}


def test_log_watch_event_emits_a_readable_stderr_message(
    tmp_path: Path, capsys
) -> None:
    """The stderr handler includes the event name and watched path."""
    log_path = tmp_path / "stderr.log"
    logger = setup_watch_logging(log_path)
    watched_path = tmp_path / "music" / "song.mp3"

    log_watch_event(logger, "file_processed", logging.INFO, path=watched_path)

    stderr = capsys.readouterr().err
    assert "file_processed" in stderr
    assert str(watched_path) in stderr


def test_setup_watch_logging_works_without_a_console_stream(tmp_path: Path) -> None:
    """Windowless Python keeps durable JSONL logging when stderr is unavailable."""
    log_path = tmp_path / "windowless.log"
    with patch.object(sys, "stderr", None):
        logger = setup_watch_logging(log_path)
        log_watch_event(logger, "service_started", logging.INFO)

    assert (
        json.loads(log_path.read_text(encoding="utf-8"))["event"] == "service_started"
    )


def test_setup_watch_logging_does_not_duplicate_file_output(tmp_path: Path) -> None:
    """Repeated setup for one path keeps exactly one file handler active."""
    log_path = tmp_path / "duplicate.log"
    first_logger = setup_watch_logging(log_path)
    second_logger = setup_watch_logging(log_path)

    log_watch_event(second_logger, "service_started", logging.INFO)

    assert first_logger is second_logger
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record == {
        "event": "service_started",
        "level": "INFO",
        "message": "service_started",
        "schema_version": 1,
        "timestamp": record["timestamp"],
    }
