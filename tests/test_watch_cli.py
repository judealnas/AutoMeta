"""Behavior tests for declarative foreground watch CLI commands."""

import os
from pathlib import Path
from unittest.mock import patch

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
                    "--recursive",
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


def test_watch_cli_rejects_invalid_command_with_nonzero_exit(tmp_path: Path) -> None:
    """Invalid watch invocation maps parser failure to a return code."""
    with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
        assert main(["watch", "add", str(tmp_path / "missing"), "--year", "2024"]) == 2
        assert main(["watch", "start", "1"]) == 2


def test_watch_run_returns_service_exit_code(tmp_path: Path) -> None:
    """The foreground command returns the service's own health exit code."""
    with patch("autometa.cli.WatchService.run", return_value=7):
        with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "store.yaml")}):
            assert main(["watch", "run"]) == 7
