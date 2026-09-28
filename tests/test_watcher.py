"""Behavior tests for the foreground reconciliation watcher service."""

from pathlib import Path
import time

from watchdog.events import (
    DirCreatedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from autometa.watch_store import WatchRule
from autometa.watcher import (
    DebounceQueue,
    EventNormalizer,
    FileStabilityProbe,
    MetadataReconciler,
    PathMatcher,
    observation_roots,
    resolve_effective_rule,
    select_observer_factory,
)


def test_auto_observer_polls_wsl_mounted_windows_roots() -> None:
    """Auto mode selects polling when WSL watches a mounted Windows drive."""
    factory = select_observer_factory(
        [Path("/mnt/c/Users/Jude/Music")], observer_mode="auto", is_wsl=True
    )

    assert factory.__name__ == "PollingObserver"
    assert (
        select_observer_factory(
            [Path("/home/jude/music")], observer_mode="auto", is_wsl=True
        ).__name__
        == "InotifyObserver"
    )


def test_path_patterns_match_relative_directories_and_globstar(tmp_path: Path) -> None:
    """Root-relative patterns distinguish direct project files from descendants."""
    root = tmp_path / "Jude Tunes"
    direct = root / "Alpha Project" / "song.mp3"
    nested = root / "Alpha Project" / "album" / "song.mp3"
    nested.parent.mkdir(parents=True)
    direct.touch()
    nested.touch()
    direct_rule = WatchRule.create(
        root=root,
        include=["* Project/*.mp3"],
        metadata={"year": "2026"},
    )
    recursive_rule = WatchRule.create(
        root=root,
        include=["* Project/**/*.mp3"],
        metadata={"year": "2026"},
    )

    assert PathMatcher(direct_rule).matches(direct)
    assert not PathMatcher(direct_rule).matches(nested)
    assert PathMatcher(recursive_rule).matches(direct)
    assert PathMatcher(recursive_rule).matches(nested)
    assert observation_roots(recursive_rule) == [root]


def test_matcher_matches_basenames_at_nested_depth_and_excludes_win(
    tmp_path: Path,
) -> None:
    """Recursive basename includes match nested files while excludes override."""
    root = tmp_path / "music"
    nested = root / "album" / "track.mp3"
    nested.parent.mkdir(parents=True)
    nested.touch()
    rule = WatchRule.create(
        root=root,
        include=["**/*.mp3"],
        exclude=["**/*.part", "**/skip*.mp3"],
        metadata={"year": "2024"},
    )
    matcher = PathMatcher(rule)

    assert matcher.matches(nested)
    assert not matcher.matches(root / "album" / "skip-track.mp3")
    assert not matcher.matches(root / "album" / "track.part")


def test_effective_rule_merges_metadata_and_prefers_higher_priority(
    tmp_path: Path,
) -> None:
    """Matching rules merge tags while higher priority overrides one tag."""
    root = tmp_path / "music"
    root.mkdir()
    path = root / "live" / "track.mp3"
    path.parent.mkdir()
    path.touch()
    base = WatchRule.create(
        root=root,
        include=["**/*.mp3"],
        priority=100,
        metadata={"artist": "Alice", "genre": "Classical"},
    )
    override = WatchRule.create(
        root=root / "live",
        priority=0,
        metadata={"genre": "Live"},
    )

    resolution = resolve_effective_rule(path, [base, override])

    assert resolution.conflicts == ()
    assert resolution.rule is not None
    assert resolution.rule.metadata == {"artist": "Alice", "genre": "Classical"}


def test_effective_rule_prefers_deeper_matching_root_at_same_priority(
    tmp_path: Path,
) -> None:
    """A scoped rule overrides a broader matching root at equal priority."""
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    path = child / "music.mp3"
    path.touch()
    broad = WatchRule.create(
        root=parent,
        include=["**/*.mp3"],
        metadata={"artist": "Broad Artist", "genre": "Jazz"},
    )
    scoped = WatchRule.create(
        root=child,
        metadata={"artist": "Scoped Artist"},
    )

    resolution = resolve_effective_rule(path, [broad, scoped])

    assert resolution.conflicts == ()
    assert resolution.rule is not None
    assert resolution.rule.metadata == {"artist": "Scoped Artist", "genre": "Jazz"}


def test_effective_rule_rejects_same_priority_conflicts(tmp_path: Path) -> None:
    """Contradictory top-priority assignments skip reconciliation safely."""
    root = tmp_path / "music"
    root.mkdir()
    path = root / "track.mp3"
    path.touch()
    jazz = WatchRule.create(root=root, priority=10, metadata={"genre": "Jazz"})
    rock = WatchRule.create(root=root, priority=10, metadata={"genre": "Rock"})

    resolution = resolve_effective_rule(path, [jazz, rock])

    assert resolution.rule is None
    assert len(resolution.conflicts) == 1
    assert resolution.conflicts[0].tag == "genre"
    assert set(resolution.conflicts[0].rule_ids) == {jazz.id, rock.id}


def test_normalizer_uses_move_destination_and_ignores_directories(
    tmp_path: Path,
) -> None:
    """Created, modified, and moved destination paths become file candidates."""
    normalizer = EventNormalizer()
    target = tmp_path / "target.mp3"

    assert normalizer.path_for(FileCreatedEvent(str(target))) == target
    assert normalizer.path_for(FileModifiedEvent(str(target))) == target
    assert normalizer.path_for(FileMovedEvent("/tmp/source.mp3", str(target))) == target
    assert normalizer.path_for(DirCreatedEvent(str(tmp_path))) is None


def test_debounce_queue_coalesces_event_storm(tmp_path: Path) -> None:
    """Repeated events for one canonical path produce one ready job."""
    queue = DebounceQueue(delay=0)
    path = tmp_path / "track.mp3"
    for _ in range(30):
        queue.put(path)

    assert queue.pop_ready() == [path.resolve()]
    assert queue.pop_ready() == []


def test_stability_probe_requires_two_unchanged_observations(tmp_path: Path) -> None:
    """A probe only accepts a file after its size and mtime settle."""
    path = tmp_path / "track.mp3"
    path.write_bytes(b"one")
    probe = FileStabilityProbe(settle_seconds=0)

    assert probe.ready(path) is False
    assert probe.ready(path) is True
    time.sleep(0.002)
    path.write_bytes(b"two")
    assert probe.ready(path) is False


def test_stability_probe_converges_for_unchanged_file(tmp_path: Path) -> None:
    """An unmodified file probed repeatedly within the settle window becomes ready.

    Regression: repeated probes were re-baselining the observation timestamp every
    call, so with the default 0.5s settle and a faster debounce cycle, ``ready()``
    never returned True and files were requeued forever.
    """
    path = tmp_path / "track.mp3"
    path.write_bytes(b"stable content")
    probe = FileStabilityProbe(settle_seconds=0.5)

    # Probe on a loop matching the worker reshape cycle; the file stays identical.
    ready = False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not ready:
        ready = probe.ready(path)
        if not ready:
            time.sleep(0.1)

    assert ready is True


def test_stability_probe_forgets_completed_and_missing_paths(tmp_path: Path) -> None:
    """Probe state is released after work completes or a path disappears."""
    path = tmp_path / "track.mp3"
    path.write_bytes(b"stable content")
    probe = FileStabilityProbe(settle_seconds=0)

    assert probe.ready(path) is False
    assert path.resolve() in probe._seen
    probe.forget(path)
    assert path.resolve() not in probe._seen

    assert probe.ready(path) is False
    path.unlink()
    assert probe.ready(path) is False
    assert path.resolve() not in probe._seen


def test_reconciler_is_idempotent_and_isolates_malformed_file(tmp_path: Path) -> None:
    """A reconciliation saves once and never lets media exceptions escape."""

    class FakeFile:
        def __init__(self) -> None:
            self.values = {"year": "2000"}
            self.saves = 0

        def __getitem__(self, key):
            return self.values.get(key.value)

        def __setitem__(self, key, value):
            self.values[key.value] = value

        def save(self) -> None:
            self.saves += 1

    fake = FakeFile()
    reconciler = MetadataReconciler(lambda _: fake)
    rule = WatchRule.create(root=tmp_path, metadata={"year": "2024"})
    path = tmp_path / "track.mp3"

    assert reconciler.reconcile(path, rule) is True
    assert reconciler.reconcile(path, rule) is False
    assert fake.saves == 1

    broken = MetadataReconciler(
        lambda _: (_ for _ in ()).throw(ValueError("bad media"))
    )
    assert broken.reconcile(path, rule) is False


def test_service_requeues_event_received_during_inflight_work(tmp_path: Path) -> None:
    """A change arriving during reconciliation schedules one follow-up pass."""
    from autometa.watch_store import RuleStore
    from autometa.watcher import WatchService

    class RecordingPool:
        def __init__(self) -> None:
            self.submissions: list[Path] = []

        def submit(self, callback, path: Path) -> None:
            self.submissions.append(path)

    class ReadyProbe:
        def ready(self, path: Path) -> bool:
            return True

        def forget(self, path: Path) -> None:
            pass

    root = tmp_path / "music"
    root.mkdir()
    path = root / "track.mp3"
    path.write_bytes(b"x")
    store = RuleStore(tmp_path / "watchers.yaml")
    store.add(WatchRule.create(root=root, metadata={"year": "2024"}))
    service = WatchService(store, debounce_delay=0)
    service._rules = store.load()
    service.probe = ReadyProbe()
    service._inflight.add(path.resolve())
    service.queue.put(path)

    pool = RecordingPool()
    service._dispatch_ready(pool)
    assert pool.submissions == []

    # Completing the original in-flight pass must preserve one later event.
    service._process(path.resolve())
    assert service.queue.pop_ready() == [path.resolve()]


def test_service_shutdown_deadline_does_not_wait_for_blocked_worker(
    tmp_path: Path,
) -> None:
    """Shutdown returns on deadline even if a reconciler call remains blocked."""
    import threading

    from autometa.watch_store import RuleStore
    from autometa.watcher import WatchService

    class Observer:
        def schedule(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return True

        def stop(self) -> None:
            pass

        def join(self) -> None:
            pass

    class BlockingReconciler:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def reconcile(self, path: Path, rule: WatchRule) -> bool:
            self.started.set()
            self.release.wait()
            return False

    root = tmp_path / "music"
    root.mkdir()
    target = root / "existing.mp3"
    target.write_bytes(b"x")
    store = RuleStore(tmp_path / "watchers.yaml")
    store.add(WatchRule.create(root=root, include=["*.mp3"], metadata={"year": "2024"}))
    reconciler = BlockingReconciler()
    service = WatchService(
        store,
        observer_factory=Observer,
        reconciler=reconciler,
        debounce_delay=0,
        shutdown_timeout=0.05,
    )
    service.probe = FileStabilityProbe(settle_seconds=0)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(service.run()))
    thread.start()
    try:
        assert reconciler.started.wait(timeout=2)
        started = time.monotonic()
        service.request_shutdown()
        thread.join(timeout=1)
        assert not thread.is_alive(), "shutdown waited for blocked worker"
        assert time.monotonic() - started < 0.5
        assert result == [0]
    finally:
        reconciler.release.set()
        thread.join(timeout=2)


def test_service_reports_observer_death_and_singleton_failure(tmp_path: Path) -> None:
    """An observer that dies is unhealthy and a second service cannot start."""
    from autometa.watch_store import RuleStore
    from autometa.watcher import WatchService, acquire_service_lock

    class DeadObserver:
        def schedule(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return False

        def stop(self) -> None:
            pass

        def join(self) -> None:
            pass

    root = tmp_path / "music"
    root.mkdir()
    store = RuleStore(tmp_path / "watchers.yaml")
    store.add(WatchRule.create(root=root, metadata={"year": "2024"}))
    assert WatchService(store, observer_factory=DeadObserver).run() == 1
    with acquire_service_lock(store.path):
        assert WatchService(store, observer_factory=DeadObserver).run() == 1


def test_service_startup_scan_reconciles_existing_file(tmp_path: Path) -> None:
    """Startup scan queues existing files even without a filesystem event."""
    from autometa.watch_store import RuleStore
    from autometa.watcher import WatchService

    class Observer:
        def schedule(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return True

        def stop(self) -> None:
            pass

        def join(self) -> None:
            pass

    root = tmp_path / "music"
    root.mkdir()
    target = root / "existing.mp3"
    target.write_bytes(b"x")
    store = RuleStore(tmp_path / "watchers.yaml")
    store.add(WatchRule.create(root=root, include=["*.mp3"], metadata={"year": "2024"}))
    seen: list[Path] = []
    reconciler = MetadataReconciler(lambda path: seen.append(path) or object())
    service = WatchService(
        store, observer_factory=Observer, reconciler=reconciler, debounce_delay=0
    )
    service.probe = FileStabilityProbe(settle_seconds=0)

    def stop_soon() -> None:
        time.sleep(0.15)
        service.request_shutdown()

    import threading

    thread = threading.Thread(target=stop_soon)
    thread.start()
    assert service.run() == 0
    thread.join()
    assert target in seen
