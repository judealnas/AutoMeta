"""Behavior tests for cross-platform watch-service management."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from autometa.service_manager import ServiceManagerError, WatchServiceManager
from autometa.watch_store import RuleStore, WatchRule


class RecordingRunner:
    """Record service-manager commands and return controlled status results."""

    def __init__(self, returncodes: list[int] | None = None) -> None:
        """Initialize the recorder.

        :param returncodes: Sequential command exit codes.
        """
        self.commands: list[list[str]] = []
        self.returncodes = iter(returncodes or [])

    def __call__(self, command: list[str]) -> CompletedProcess[str]:
        """Record a command and return its configured completion.

        :param command: Command supplied by the service backend.
        :return: Synthetic command result.
        """
        self.commands.append(command)
        return CompletedProcess(command, next(self.returncodes, 0), "active\n", "")


def _store_with_rule(tmp_path: Path) -> RuleStore:
    """Create a populated rule store for service-manager tests.

    :param tmp_path: Pytest temporary directory.
    :return: Populated rule store.
    """
    root = tmp_path / "music"
    root.mkdir()
    store = RuleStore(tmp_path / "watchers.yaml")
    store.add(WatchRule.create(root=root, metadata={"year": "2024"}))
    return store


def test_linux_start_writes_user_unit_manifest_and_starts_service(
    tmp_path: Path,
) -> None:
    """Linux start writes a systemd user unit bound to the exact watch store."""
    store = _store_with_rule(tmp_path)
    runner = RecordingRunner()
    manager = WatchServiceManager(
        store,
        platform_name="Linux",
        home=tmp_path / "home",
        command_runner=runner,
    )

    status = manager.start()

    unit = tmp_path / "home" / ".config/systemd/user" / f"{status.name}.service"
    assert status.backend == "systemd"
    assert status.installed is True
    assert unit.is_file()
    unit_text = unit.read_text()
    assert "AUTOMETA_WATCH_STORE=" in unit_text
    assert str(store.path) in unit_text
    assert "watch run --observer auto" in unit_text
    assert manager.manifest_path.is_file()
    assert runner.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", status.name],
    ]


def test_macos_start_writes_launch_agent_and_bootstraps_it(tmp_path: Path) -> None:
    """macOS start writes a LaunchAgent and loads it in the current GUI domain."""
    store = _store_with_rule(tmp_path)
    runner = RecordingRunner()
    manager = WatchServiceManager(
        store,
        platform_name="Darwin",
        home=tmp_path / "home",
        uid=501,
        command_runner=runner,
    )

    status = manager.start()

    plist = tmp_path / "home/Library/LaunchAgents" / f"{status.name}.plist"
    assert status.backend == "launchd"
    assert plist.is_file()
    assert "AUTOMETA_WATCH_STORE" in plist.read_text()
    assert runner.commands == [
        ["launchctl", "bootout", f"gui/501/{status.name}"],
        ["launchctl", "bootstrap", "gui/501", str(plist)],
    ]


def test_windows_start_creates_and_runs_user_task(tmp_path: Path) -> None:
    """Windows start creates a logon task without requiring elevation."""
    store = _store_with_rule(tmp_path)
    runner = RecordingRunner()
    manager = WatchServiceManager(
        store,
        platform_name="Windows",
        home=tmp_path / "home",
        command_runner=runner,
    )

    status = manager.start()

    assert status.backend == "schtasks"
    task_xml = tmp_path / "watchers.task.xml"
    assert task_xml.is_file()
    task_text = task_xml.read_text(encoding="utf-16")
    assert "<Hidden>true</Hidden>" in task_text
    assert "<LogonTrigger>" in task_text
    assert "AUTOMETA_WATCH_STORE" in task_text
    assert runner.commands[0] == [
        "schtasks",
        "/Create",
        "/TN",
        status.name,
        "/XML",
        str(task_xml),
        "/F",
    ]
    assert runner.commands[1] == ["schtasks", "/Run", "/TN", status.name]


def test_status_stop_and_uninstall_use_persisted_backend(tmp_path: Path) -> None:
    """Lifecycle operations retain the installed backend rather than redetecting it."""
    store = _store_with_rule(tmp_path)
    runner = RecordingRunner()
    manager = WatchServiceManager(
        store,
        platform_name="Linux",
        home=tmp_path / "home",
        command_runner=runner,
    )
    status = manager.start()
    runner.commands.clear()

    assert manager.status().running is True
    manager.stop()
    manager.uninstall()

    assert runner.commands == [
        ["systemctl", "--user", "is-active", status.name],
        ["systemctl", "--user", "disable", "--now", status.name],
        ["systemctl", "--user", "disable", "--now", status.name],
        ["systemctl", "--user", "daemon-reload"],
    ]
    assert not manager.manifest_path.exists()


def test_start_rejects_empty_rule_store(tmp_path: Path) -> None:
    """A background service cannot be installed until at least one rule exists."""
    manager = WatchServiceManager(
        RuleStore(tmp_path / "watchers.yaml"),
        platform_name="Linux",
        home=tmp_path / "home",
        command_runner=RecordingRunner(),
    )

    with pytest.raises(ServiceManagerError, match="at least one watch rule"):
        manager.start()
