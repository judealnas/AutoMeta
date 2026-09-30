"""End-to-end tests for the top-level structured log CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from autometa.cli import main
from autometa.watch_logging import get_watch_log_path
from autometa.watch_store import ENV_STORE_PATH


def _write_log(path: Path, records: list[dict[str, object]]) -> None:
    """Create an active JSONL watch log for a CLI test.

    :param path: Active log-file path.
    :type path: pathlib.Path
    :param records: Records to serialize as JSONL.
    :type records: list[dict[str, object]]
    :return: None.
    :rtype: None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_logs_path_prints_the_canonical_store_sibling(tmp_path: Path, capsys) -> None:
    """The path mode explains exactly where the selected store's log is located.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    :param capsys: Pytest standard-stream capture fixture.
    :type capsys: pytest.CaptureFixture[str]
    """
    store = tmp_path / "watchers.yaml"

    old_store = os.environ.get(ENV_STORE_PATH)
    os.environ[ENV_STORE_PATH] = str(store)
    try:
        assert main(["logs", "path"]) == 0
    finally:
        if old_store is None:
            os.environ.pop(ENV_STORE_PATH, None)
        else:
            os.environ[ENV_STORE_PATH] = old_store

    assert capsys.readouterr().out.strip() == str(get_watch_log_path(store))


def test_logs_filters_json_output_and_summary(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Filters preserve JSON output while summaries count the selected records.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    :param capsys: Pytest standard-stream capture fixture.
    :type capsys: pytest.CaptureFixture[str]
    :param monkeypatch: Pytest environment patch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    """
    store = tmp_path / "watchers.yaml"
    log_path = get_watch_log_path(store)
    _write_log(
        log_path,
        [
            {
                "event": "watch.metadata_updated",
                "level": "INFO",
                "path": "/music/a.mp3",
                "rule_ids": ["rule-a"],
                "timestamp": "2026-09-30T00:00:00Z",
            },
            {
                "event": "watch.reconciliation_failed",
                "level": "ERROR",
                "path": "/music/b.mp3",
                "rule_ids": ["rule-b"],
                "timestamp": "2026-09-30T00:01:00Z",
            },
        ],
    )
    monkeypatch.setenv(ENV_STORE_PATH, str(store))

    assert (
        main(
            [
                "logs",
                "--event",
                "watch.reconciliation_failed",
                "--path",
                "b.mp3",
                "--rule",
                "rule-b",
                "--level",
                "ERROR",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "event": "watch.reconciliation_failed",
        "level": "ERROR",
        "path": "/music/b.mp3",
        "rule_ids": ["rule-b"],
        "timestamp": "2026-09-30T00:01:00Z",
    }

    assert main(["logs", "summary", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "events": {
            "watch.metadata_updated": 1,
            "watch.reconciliation_failed": 1,
        },
        "levels": {"ERROR": 1, "INFO": 1},
        "total": 2,
    }


def test_logs_file_failures_and_clear_modes(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Dedicated file/failure views filter history and clear needs explicit consent.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    :param capsys: Pytest standard-stream capture fixture.
    :type capsys: pytest.CaptureFixture[str]
    :param monkeypatch: Pytest environment patch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    """
    store = tmp_path / "watchers.yaml"
    log_path = get_watch_log_path(store)
    _write_log(
        log_path,
        [
            {
                "event": "watch.metadata_updated",
                "level": "INFO",
                "path": "/music/a.mp3",
                "timestamp": "2026-09-30T00:00:00Z",
            },
            {
                "event": "watch.reconciliation_failed",
                "level": "ERROR",
                "path": "/music/b.mp3",
                "timestamp": "2026-09-30T00:01:00Z",
            },
        ],
    )
    _write_log(log_path.with_name(f"{log_path.name}.1"), [])
    monkeypatch.setenv(ENV_STORE_PATH, str(store))

    assert main(["logs", "file", "/music/b.mp3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "watch.reconciliation_failed"

    assert main(["logs", "failures", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"
    assert main(["logs", "failures", "--level", "INFO"]) == 2

    assert main(["logs", "clear"]) == 2
    assert log_path.is_file()
    assert main(["logs", "clear", "--yes"]) == 0
    assert not log_path.exists()
    assert not log_path.with_name(f"{log_path.name}.1").exists()


def test_logs_tail_renders_human_readable_records(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Default terminal output is concise and tail limits it to newest entries.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    :param capsys: Pytest standard-stream capture fixture.
    :type capsys: pytest.CaptureFixture[str]
    :param monkeypatch: Pytest environment patch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    """
    store = tmp_path / "watchers.yaml"
    _write_log(
        get_watch_log_path(store),
        [
            {
                "event": "watch.path_queued",
                "level": "INFO",
                "path": "/music/a.mp3",
                "timestamp": "2026-09-30T00:00:00Z",
            },
            {
                "event": "watch.metadata_updated",
                "level": "INFO",
                "path": "/music/b.mp3",
                "timestamp": "2026-09-30T00:01:00Z",
            },
        ],
    )
    monkeypatch.setenv(ENV_STORE_PATH, str(store))

    assert main(["logs", "--tail", "1"]) == 0

    output = capsys.readouterr().out.strip()
    assert "watch.metadata_updated" in output
    assert "/music/b.mp3" in output
    assert "watch.path_queued" not in output
