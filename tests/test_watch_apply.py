"""Behavior tests for applying user-authored watch rule files."""

import os
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from autometa.cli import main
from autometa.watch_store import ENV_STORE_PATH, RuleStore
from autometa.watcher import WatchService, resolve_effective_rule


def test_apply_creates_named_rules_with_relative_roots(tmp_path: Path) -> None:
    """One file creates overlapping rules with an inherited and a scoped root.

    :param tmp_path: Isolated directory for the rule source, roots, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    (root / "live").mkdir(parents=True)
    source = tmp_path / "my-watch.yaml"
    source.write_text(
        "version: 1\n"
        "root: music\n"
        "rules:\n"
        "  - name: defaults\n"
        "    include: ['**/*.mp3']\n"
        "    metadata: {genre: Classical}\n"
        "  - name: live\n"
        "    root: music/live\n"
        "    include: ['*.mp3']\n"
        "    priority: 100\n"
        "    metadata: {genre: Live, year: 2025}\n"
    )
    store = tmp_path / "state" / "watchers.yaml"

    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "apply", str(source)]) == 0

    rules = RuleStore(store).load()
    assert len(rules) == 2
    assert [rule.root for rule in rules] == [
        str(root.resolve()),
        str((root / "live").resolve()),
    ]
    assert [rule.priority for rule in rules] == [0, 100]
    assert [rule.metadata for rule in rules] == [
        {"genre": "Classical"},
        {"genre": "Live", "year": "2025"},
    ]
    assert all(rule.source == str(source.resolve()) for rule in rules)
    resolution = resolve_effective_rule(root / "live" / "song.mp3", rules)
    assert resolution.rule is not None
    assert resolution.rule.metadata == {"genre": "Live", "year": "2025"}


def test_reapply_replaces_only_its_own_rules_and_keeps_retained_ids(
    tmp_path: Path,
) -> None:
    """Reapplying removes omitted names but leaves CLI and other sources alone.

    :param tmp_path: Isolated source files, root, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(
        f"version: 1\nroot: '{root}'\nrules:\n"
        "  - name: keep\n    metadata: {year: 2024}\n"
        "  - name: drop\n    metadata: {genre: Jazz}\n"
    )
    second.write_text(
        f"version: 1\nroot: '{root}'\nrules:\n"
        "  - name: other\n    metadata: {title: Other}\n"
    )
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "add", str(root), "--artist", "CLI"]) == 0
        assert main(["watch", "apply", str(first)]) == 0
        assert main(["watch", "apply", str(second)]) == 0
        before = RuleStore(store).load()
        cli_id, keep_id, drop_id, other_id = [rule.id for rule in before]

        first.write_text(
            f"version: 1\nroot: '{root}'\nrules:\n"
            "  - name: keep\n    priority: 10\n    metadata: {year: 2025}\n"
        )
        assert main(["watch", "apply", str(first)]) == 0
        after = RuleStore(store).load()

        assert {rule.id for rule in after} == {cli_id, keep_id, other_id}
        assert drop_id not in {rule.id for rule in after}
        assert next(rule for rule in after if rule.id == keep_id).metadata == {
            "year": "2025"
        }
        assert next(rule for rule in after if rule.id == keep_id).priority == 10
        assert next(rule for rule in after if rule.id == cli_id) == before[0]
        assert next(rule for rule in after if rule.id == other_id) == before[3]

        first.write_text("version: 1\nrules: []\n")
        assert main(["watch", "apply", str(first)]) == 0
        assert {rule.id for rule in RuleStore(store).load()} == {cli_id, other_id}


def test_reapplying_unchanged_file_does_not_rewrite_store_after_another_source(
    tmp_path: Path,
) -> None:
    """An unchanged source is idempotent even if another source applied later.

    :param tmp_path: Isolated rule roots, sources, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(
        "version: 1\nroot: music\nrules:\n  - name: alpha\n    metadata: {year: 2025}\n"
    )
    second.write_text(
        "version: 1\nroot: music\nrules:\n  - name: beta\n    metadata: {genre: Folk}\n"
    )
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "apply", str(first)]) == 0
        assert main(["watch", "apply", str(second)]) == 0
        baseline = RuleStore(store)
        baseline.load()
        assert main(["watch", "apply", str(first)]) == 0
        assert baseline.changed() is False


@pytest.mark.parametrize(
    "bad_rule",
    [
        "    include: null\n    metadata: {genre: Jazz}\n",
        "    metadata: {year: true}\n",
        "    unknown: typo\n    metadata: {genre: Jazz}\n",
        "    metadata: {unknown_tag: Jazz}\n",
        "    root: missing\n    metadata: {genre: Jazz}\n",
    ],
)
def test_invalid_rule_file_does_not_change_existing_rules(
    tmp_path: Path, bad_rule: str, capsys
) -> None:
    """A bad rule late in the file cannot cause a partial replacement.

    :param tmp_path: Isolated source, root, and store.
    :type tmp_path: Path
    :param bad_rule: Invalid YAML fields to test.
    :type bad_rule: str
    :param capsys: Pytest output capture.
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    source = tmp_path / "rules.yaml"
    store = tmp_path / "watchers.yaml"
    source.write_text(
        "version: 1\nroot: music\nrules:\n"
        "  - name: stable\n    metadata: {genre: Classical}\n"
    )
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "apply", str(source)]) == 0
        before = store.read_bytes()
        source.write_text(
            "version: 1\nroot: music\nrules:\n"
            "  - name: stable\n    metadata: {genre: New}\n"
            "  - name: broken\n" + bad_rule
        )
        assert main(["watch", "apply", str(source)]) == 2
        assert store.read_bytes() == before
        assert "error" in capsys.readouterr().err


def test_duplicate_yaml_fields_are_rejected_without_store_changes(
    tmp_path: Path,
) -> None:
    """Repeated YAML mapping keys cannot silently override intended rules.

    :param tmp_path: Isolated source, root, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    source = tmp_path / "rules.yaml"
    source.write_text(
        "version: 1\nroot: music\nrules:\n"
        "  - name: defaults\n    priority: 100\n    priority: 0\n"
        "    metadata: {genre: Jazz}\n"
    )
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "apply", str(source)]) == 2
    assert not store.exists()


def test_missing_source_does_not_remove_previously_applied_rules(
    tmp_path: Path,
) -> None:
    """Removing a source file is an error, not an empty rule document.

    :param tmp_path: Isolated source, root, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    source = tmp_path / "rules.yaml"
    source.write_text(
        "version: 1\nroot: music\nrules:\n"
        "  - name: genre\n    metadata: {genre: Jazz}\n"
    )
    store = tmp_path / "watchers.yaml"
    with patch.dict(os.environ, {ENV_STORE_PATH: str(store)}):
        assert main(["watch", "apply", str(source)]) == 0
        before = store.read_bytes()
        source.unlink()
        assert main(["watch", "apply", str(source)]) == 2
        assert store.read_bytes() == before


def test_running_watch_service_reloads_applied_rules(tmp_path: Path) -> None:
    """A successful apply is detected by the already-running watch service.

    :param tmp_path: Isolated rule source, root, and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """

    class Observer:
        """Minimal live observer for testing the service's reload loop."""

        def schedule(self, *args, **kwargs) -> None:
            """Accept scheduled roots without starting a real filesystem watcher."""

        def start(self) -> None:
            """Mark observer startup so the test can apply after service load."""
            ready.set()

        def is_alive(self) -> bool:
            """Keep the service alive until explicitly stopped.

            :return: True while the test runs.
            :rtype: bool
            """
            return True

        def stop(self) -> None:
            """Allow clean service shutdown."""

        def join(self) -> None:
            """Allow clean service shutdown."""

    class ReadyProbe:
        """Treat the test file as settled immediately after the rescan."""

        def ready(self, path: Path) -> bool:
            """Accept any queued test file.

            :param path: File scheduled by the service.
            :type path: Path
            :return: True for every test file.
            :rtype: bool
            """
            return True

        def forget(self, path: Path) -> None:
            """Discard test-file stability state.

            :param path: Completed path.
            :type path: Path
            :return: None.
            :rtype: None
            """

        def clear(self) -> None:
            """Reset stability state after the store reload."""

    class Recorder:
        """Record reconciliation of the applied metadata."""

        def reconcile(self, path: Path, rule) -> bool:
            """Observe the file and effective rule selected after reload.

            :param path: Reconciled file.
            :type path: Path
            :param rule: Effective watch rule.
            :return: False to simulate metadata already being current.
            :rtype: bool
            """
            seen.append((path, rule.metadata))
            reconciled.set()
            return False

    root = tmp_path / "music"
    root.mkdir()
    target = root / "track.mp3"
    target.write_bytes(b"test")
    source = tmp_path / "rules.yaml"
    source.write_text(
        "version: 1\nroot: music\nrules:\n"
        "  - name: genre\n    metadata: {genre: Jazz}\n"
    )
    store_path = tmp_path / "watchers.yaml"
    ready = threading.Event()
    reconciled = threading.Event()
    seen: list[tuple[Path, dict]] = []
    service = WatchService(
        RuleStore(store_path), observer_factory=Observer, reconciler=Recorder()
    )
    service.probe = ReadyProbe()
    result: list[int] = []
    worker = threading.Thread(target=lambda: result.append(service.run()))
    worker.start()
    try:
        assert ready.wait(timeout=2)
        with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
            assert main(["watch", "apply", str(source)]) == 0
        assert reconciled.wait(timeout=2)
        assert len(service._rules) == 1
        assert service._rules[0].metadata == {"genre": "Jazz"}
    finally:
        service.request_shutdown()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert result == [0]
    assert seen == [(target, {"genre": "Jazz"})]


def test_watch_list_identifies_file_owned_rules(tmp_path: Path, capsys) -> None:
    """A user can distinguish applied rules from manually added rules.

    :param tmp_path: Isolated rule source, root, and store.
    :type tmp_path: Path
    :param capsys: Captured CLI output.
    :return: None.
    :rtype: None
    """
    root = tmp_path / "music"
    root.mkdir()
    source = tmp_path / "rules.yaml"
    source.write_text(
        "version: 1\nroot: music\nrules:\n"
        "  - name: genre\n    metadata: {genre: Jazz}\n"
    )
    with patch.dict(os.environ, {ENV_STORE_PATH: str(tmp_path / "watchers.yaml")}):
        assert main(["watch", "apply", str(source)]) == 0
        capsys.readouterr()
        assert main(["watch", "list"]) == 0
    assert f"source={source.resolve()}" in capsys.readouterr().out
