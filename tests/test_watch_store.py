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
        recursive=True,
        metadata={"artist": ["Alice"], "year": "2024"},
    )

    assert rule.root == str(root.resolve())
    assert rule.include == ["*.mp3"]
    assert rule.exclude == ["*.part"]
    assert rule.recursive is True
    assert rule.metadata == {"artist": ["Alice"], "year": "2024"}
    assert len(rule.id) == 36

    with pytest.raises(ValueError, match="directory"):
        WatchRule.create(root=tmp_path / "missing", metadata={"year": "2024"})
    with pytest.raises(ValueError, match="Unknown metadata tag"):
        WatchRule.create(root=root, metadata={"nope": "x"})
    with pytest.raises(ValueError, match="metadata"):
        WatchRule.create(root=root, metadata={})


def test_rule_store_add_remove_reload_and_atomic_yaml(tmp_path: Path) -> None:
    """A store atomically persists rules and detects later replacements."""
    from autometa.watch_store import RuleStore

    root = tmp_path / "music"
    root.mkdir()
    store_path = tmp_path / "watchers.yaml"
    store = RuleStore(store_path)
    rule = WatchRule.create(root=root, metadata={"year": "2024"})

    store.add(rule)
    assert store.load() == [rule]
    assert "version: 2" in store_path.read_text()
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
