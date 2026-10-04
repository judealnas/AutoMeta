"""Behavior tests for declarative watch rule persistence."""

from pathlib import Path

import pytest

from autometa.watch_store import WatchRule


def test_watch_rule_validates_directory_and_known_nonempty_metadata(
    tmp_path: Path,
) -> None:
    """A rule stores a UUID-shaped ID and normalized metadata."""
    root = tmp_path / "music"
    root.mkdir()

    rule = WatchRule.create(
        root=root,
        include=["*.mp3"],
        exclude=["*.part"],
        metadata={"artist": ["Alice"], "year": "2024"},
    )

    assert rule.root == str(root.resolve())
    assert rule.include == ["*.mp3"]
    assert rule.exclude == ["*.part"]
    assert rule.metadata == {"artist": ["Alice"], "year": "2024"}
    assert len(rule.id) == 36

    with pytest.raises(ValueError, match="directory"):
        WatchRule.create(root=tmp_path / "missing", metadata={"year": "2024"})
    with pytest.raises(ValueError, match="Unknown metadata tag"):
        WatchRule.create(root=root, metadata={"nope": "x"})
    with pytest.raises(ValueError, match="metadata"):
        WatchRule.create(root=root, metadata={})


def test_rule_store_migrates_recursive_v2_patterns_to_path_globs(
    tmp_path: Path,
) -> None:
    """Version-two basename rules load as equivalent current-version glob rules."""
    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    store_path = tmp_path / "watchers.yaml"
    store_path.write_text(
        "version: 2\n"
        "rules:\n"
        "  - id: 12345678-1234-4567-8123-123456789abc\n"
        f"    root: {root}\n"
        "    include: ['*.mp3']\n"
        "    exclude: ['*.part']\n"
        "    recursive: true\n"
        "    priority: 0\n"
        "    metadata: {year: '2024'}\n"
    )

    rules = RuleStore(store_path).load()

    assert rules[0].include == ["**/*.mp3"]
    assert rules[0].exclude == ["**/*.part"]
    assert not hasattr(rules[0], "recursive")


def test_rule_store_reads_version_three_and_upgrades_on_write(tmp_path: Path) -> None:
    """Older watch state remains readable before the next atomic write.

    :param tmp_path: Directory for a legacy rule root and store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    path = tmp_path / "watchers.yaml"
    path.write_text(
        "version: 3\nrules:\n"
        "  - id: 12345678-1234-4567-8123-123456789abc\n"
        f"    root: {root}\n"
        "    include: ['*.mp3']\n"
        "    metadata: {year: '2024'}\n"
    )
    store = RuleStore(path)
    legacy = store.load()[0]
    assert legacy.source is None
    store.add(WatchRule.create(root=root, metadata={"genre": "Jazz"}))
    assert "version: 4" in path.read_text()
    assert store.load()[0] == legacy


def test_store_rejects_invalid_source_provenance(tmp_path: Path) -> None:
    """Corrupted ownership metadata cannot silently become a different owner.

    :param tmp_path: Directory containing a rule root and malformed store.
    :type tmp_path: Path
    :return: None.
    :rtype: None
    """
    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    path = tmp_path / "watchers.yaml"
    path.write_text(
        "version: 4\nrules:\n"
        "  - id: 12345678-1234-4567-8123-123456789abc\n"
        f"    root: {root}\n"
        "    metadata: {year: '2024'}\n"
        "    source: false\n"
    )
    with pytest.raises(ValueError, match="source"):
        RuleStore(path).load()


def test_windows_store_lock_releases_the_same_byte_range(
    tmp_path: Path, monkeypatch
) -> None:
    """Windows lock release uses the exact byte range acquired for the store lock."""
    import os
    import sys
    import types

    from autometa import watch_store
    from autometa.watch_store import RuleStore

    operations: list[tuple[int, int]] = []
    fake_msvcrt = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=2)

    def locking(descriptor: int, mode: int, size: int) -> None:
        """Record the offset used by a simulated ``msvcrt.locking`` call."""
        operations.append((mode, os.lseek(descriptor, 0, os.SEEK_CUR)))

    fake_msvcrt.locking = locking
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(watch_store, "_is_windows", lambda: True)
    store = RuleStore(tmp_path / "watchers.yaml")

    with store._locked():
        pass

    assert operations == [(fake_msvcrt.LK_LOCK, 0), (fake_msvcrt.LK_UNLCK, 0)]


def test_rule_store_add_remove_reload_and_atomic_yaml(
    tmp_path: Path, monkeypatch
) -> None:
    """A store atomically persists rules, fsyncs its directory, and reloads."""
    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    store_path = tmp_path / "watchers.yaml"
    store = RuleStore(store_path)
    rule = WatchRule.create(root=root, metadata={"year": "2024"})
    fsynced_directories: list[Path] = []
    monkeypatch.setattr(
        store,
        "_fsync_directory",
        lambda directory: fsynced_directories.append(directory),
    )

    store.add(rule)
    assert fsynced_directories == [store_path.parent]
    assert store.load() == [rule]
    assert "version: 4" in store_path.read_text()
    assert store.changed() is False

    replacement = WatchRule.create(root=root, metadata={"title": "New"})
    RuleStore(store_path).add(replacement)
    assert store.changed() is True
    assert store.reload() == [rule, replacement]
    assert store.remove(rule.id) is True
    assert store.load() == [replacement]
    assert store.remove(rule.id) is False


def test_rule_store_rejects_duplicate_ids_and_safe_concurrent_updates(
    tmp_path: Path,
) -> None:
    """Store validation catches duplicate IDs and locking preserves all adds."""
    from concurrent.futures import ThreadPoolExecutor

    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    store_path = tmp_path / "watchers.yaml"
    fixed = WatchRule.create(
        root=root,
        metadata={"year": "2024"},
        id="12345678-1234-4567-8123-123456789abc",
    )
    store = RuleStore(store_path)
    store.add(fixed)
    with pytest.raises(ValueError, match="Duplicate"):
        store.add(fixed)

    def add_one(index: int) -> None:
        RuleStore(store_path).add(
            WatchRule.create(root=root, metadata={"title": str(index)})
        )

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(add_one, range(8)))
    assert len(RuleStore(store_path).load()) == 9
