"""Behavior tests for declarative foreground watch CLI commands."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from autometa.cli import main
from autometa.watch_store import ENV_STORE_PATH, RuleStore


def test_watch_add_list_and_remove_return_statuses(tmp_path: Path, capsys) -> None:
    """Watch management creates UUID rules, lists them, and removes by ID."""
    root = tmp_path / "music"
    root.mkdir()
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert (
            main(
                [
                    "watch",
                    "add",
                    str(root),
                    "--include",
                    "*.mp3",
                    "--artist",
                    "Alice,Bob",
                    "--year",
                    "2024",
                ]
            )
            == 0
        )
        rules = RuleStore(store).load()
        assert len(rules) == 1
        rule_id = rules[0].id
        assert main(["watch", "list"]) == 0
        assert rule_id in capsys.readouterr().out
        assert main(["watch", "remove", rule_id]) == 0
        assert RuleStore(store).load() == []
        assert main(["watch", "remove", rule_id]) == 1


def test_watch_priority_is_persisted_and_updated(tmp_path: Path) -> None:
    """Priority defaults to zero and can be changed without replacing metadata."""
    root = tmp_path / "music"
    root.mkdir()
    store = tmp_path / "watchers.yaml"

    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "add", str(root), "--year", "2024"]) == 0
        rule = RuleStore(store).load()[0]
        assert rule.priority == 0
        assert main(["watch", "update", rule.id, "--priority", "100"]) == 0
        rule = RuleStore(store).load()[0]
        assert rule.priority == 100
        assert rule.metadata == {"year": "2024"}


def test_watch_update_replaces_supplied_fields_and_preserves_others(
    tmp_path: Path,
) -> None:
    """Update replaces supplied values and clears lists only on explicit flags."""
    root = tmp_path / "music"
    replacement_root = tmp_path / "replacement"
    root.mkdir()
    replacement_root.mkdir()
    store = tmp_path / "watchers.yaml"

    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert (
            main(
                [
                    "watch",
                    "add",
                    str(root),
                    "--include",
                    "*.mp3",
                    "--include",
                    "*.flac",
                    "--exclude",
                    "*.part",
                    "--artist",
                    "Alice,Bob",
                    "--year",
                    "2024",
                ]
            )
            == 0
        )
        rule_id = RuleStore(store).load()[0].id

        # Scalars and supplied pattern lists replace; omitted fields survive.
        assert (
            main(
                [
                    "watch",
                    "update",
                    rule_id,
                    "--root",
                    str(replacement_root),
                    "--include",
                    "*.ogg",
                    "--year",
                    "2025",
                ]
            )
            == 0
        )
        rule = RuleStore(store).load()[0]
        assert rule.root == str(replacement_root.resolve())
        assert rule.include == ["*.ogg"]
        assert rule.exclude == ["*.part"]
        assert rule.metadata == {"artist": ["Alice", "Bob"], "year": "2025"}

        # Empty lists require explicit clear flags.
        assert (
            main(["watch", "update", rule_id, "--clear-include", "--clear-exclude"])
            == 0
        )
        rule = RuleStore(store).load()[0]
        assert rule.include == []
        assert rule.exclude == []


def test_watch_update_rejects_conflicting_list_options(tmp_path: Path) -> None:
    """Clear and replacement flags for a list cannot be combined."""
    with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
        assert (
            main(["watch", "update", "id", "--include", "*.mp3", "--clear-include"])
            == 2
        )
        assert (
            main(["watch", "update", "id", "--exclude", "*.part", "--clear-exclude"])
            == 2
        )


def test_watch_cli_rejects_invalid_command_with_nonzero_exit(tmp_path: Path) -> None:
    """Invalid watch invocation maps parser failure to a return code."""
    with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
        assert main(["watch", "add", str(tmp_path / "missing"), "--year", "2024"]) == 2
        assert main(["watch", "start", "1"]) == 2


def test_watch_start_delegates_to_platform_service_manager(
    tmp_path: Path, capsys
) -> None:
    """Start installs and launches the managed platform service."""
    from autometa.service_manager import ServiceStatus

    with patch("autometa.cli.WatchServiceManager") as manager_type:
        manager_type.return_value.start.return_value = ServiceStatus(
            "systemd", "autometa-watch-test", installed=True, running=True
        )
        with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
            assert main(["watch", "start"]) == 0

    assert "started systemd service autometa-watch-test" in capsys.readouterr().out


def test_watch_run_accepts_explicit_observer_mode(tmp_path: Path) -> None:
    """Foreground operation can force polling or native watchdog events."""
    with patch("autometa.cli.WatchService.run", return_value=0) as run:
        with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
            assert main(["watch", "run", "--observer", "polling"]) == 0

    assert run.call_args.kwargs == {}
    assert run.call_args.args == ()


def test_watch_run_returns_service_exit_code(tmp_path: Path) -> None:
    """The foreground command returns the service's own health exit code."""
    with patch("autometa.cli.WatchService.run", return_value=7):
        with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
            assert main(["watch", "run"]) == 7


def test_watch_run_service_terminates_cleanly_on_sigterm(tmp_path: Path) -> None:
    """SIGTERM to a running ``watch run`` service yields a clean zero exit.

    The service's shutdown signal handler must be registered, otherwise the
    process is killed by SIGTERM with status 143 instead of exiting gracefully.
    """
    if os.name == "nt":
        pytest.skip("Windows does not provide POSIX SIGTERM process semantics.")
    import signal
    import subprocess
    import time

    root = tmp_path / "music"
    root.mkdir()
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert (
            main(["watch", "add", str(root), "--include", "*.mp3", "--year", "2024"])
            == 0
        )

    env = dict(os.environ, AUTOMETA_WATCH_STORE=str(store), PYTHONPATH=str(tmp_path))
    proc = subprocess.Popen(
        ["uv", "run", "autometa", "watch", "run"],
        env=env,
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Give the service a moment to acquire its lock and start observing.
        time.sleep(1.5)
        assert proc.poll() is None, f"service exited early: {proc.stderr.read()}"
        os.kill(proc.pid, signal.SIGTERM)
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise AssertionError("service hung on SIGTERM (handler not registered)")
        assert code == 0, f"expected clean exit 0, got {code}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
