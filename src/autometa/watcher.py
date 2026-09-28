"""Foreground filesystem reconciliation service for declarative watch rules."""

from __future__ import annotations

from fnmatch import fnmatch
import contextlib
from dataclasses import dataclass
import logging
from pathlib import Path
import queue
import signal
import threading
import time
from typing import Callable, Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from autometa.core import MusicFile
from autometa.tags import Tags
from autometa.watch_store import RuleStore, WatchRule

LOGGER = logging.getLogger(__name__)


def _is_wsl() -> bool:
    """Return whether this Linux process is running under WSL.

    :return: Whether the current environment is Windows Subsystem for Linux.
    """
    if __import__("os").environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def _is_wsl_windows_mount(path: Path) -> bool:
    """Return whether a path uses the conventional WSL Windows-drive mount.

    :param path: Candidate watch root.
    :return: Whether the path is beneath ``/mnt/<drive>``.
    """
    parts = path.expanduser().resolve().parts
    return len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1


def select_observer_factory(
    roots: Iterable[Path], *, observer_mode: str = "auto", is_wsl: bool | None = None
) -> Callable[[], Observer]:
    """Choose native or polling watchdog observation for configured roots.

    :param roots: Rule roots that will be scheduled by the observer.
    :param observer_mode: ``auto``, ``native``, or ``polling``.
    :param is_wsl: Optional environment override for testing.
    :return: Zero-argument watchdog observer constructor.
    :raises ValueError: If observer_mode is unsupported.
    """
    if observer_mode == "polling":
        return PollingObserver
    if observer_mode == "native":
        return Observer
    if observer_mode != "auto":
        raise ValueError(f"Unknown observer mode: {observer_mode}")
    running_in_wsl = _is_wsl() if is_wsl is None else is_wsl
    if running_in_wsl and any(_is_wsl_windows_mount(root) for root in roots):
        return PollingObserver
    return Observer


class PathMatcher:
    """Apply one rule's explicit path matching semantics."""

    def __init__(self, rule: WatchRule) -> None:
        """Initialize a matcher.

        :param rule: Rule defining root and include/exclude patterns.
        """
        self.rule = rule
        self.root = Path(rule.root)

    def matches(self, path: Path) -> bool:
        """Return whether a file is accepted by the rule.

        Basename patterns such as ``*.mp3`` match every watched depth; patterns
        containing a slash are matched against the relative POSIX path.

        :param path: Candidate filesystem path.
        :return: Whether it is included and not excluded.
        """
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        if not self.rule.recursive and len(relative.parts) != 1:
            return False
        candidate = relative.as_posix()
        basename = relative.name

        def matches_pattern(pattern: str) -> bool:
            """Match basename patterns at all depths and slash patterns relatively.

            :param pattern: Include or exclude glob pattern.
            :return: Whether the candidate matches it.
            """
            return fnmatch(candidate if "/" in pattern else basename, pattern)

        return any(
            matches_pattern(pattern) for pattern in self.rule.include
        ) and not any(matches_pattern(pattern) for pattern in self.rule.exclude)


@dataclass(frozen=True)
class EffectiveRule:
    """Merged desired metadata for a path after rule precedence is resolved."""

    id: str
    metadata: dict[str, str | list[str]]


@dataclass(frozen=True)
class RuleConflict:
    """Same-priority, incompatible metadata assignments for one tag."""

    tag: str
    priority: int
    rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class RuleResolution:
    """The effective metadata rule or conflicts blocking reconciliation."""

    rule: EffectiveRule | None
    conflicts: tuple[RuleConflict, ...]


def resolve_effective_rule(path: Path, rules: Iterable[WatchRule]) -> RuleResolution:
    """Merge matching rules by priority and root specificity.

    Higher-priority assignments replace lower-priority assignments for the same
    tag. At equal priority, a rule with a deeper root takes precedence. Different
    values at equal priority and equal root depth are conflicts, so the caller
    must skip the path rather than choosing an arbitrary writer.

    :param path: Candidate media file.
    :param rules: Configured watch rules to evaluate.
    :return: Effective rule or the conflicts that prevent reconciliation.
    """
    selected: dict[str, tuple[int, int, str | list[str], set[str]]] = {}
    conflicts: dict[str, RuleConflict] = {}
    for rule in rules:
        if not PathMatcher(rule).matches(path):
            continue
        root_depth = len(Path(rule.root).parts)
        for tag, value in rule.metadata.items():
            existing = selected.get(tag)
            precedence = (rule.priority, root_depth)
            if existing is None or precedence > existing[:2]:
                selected[tag] = (rule.priority, root_depth, value, {rule.id})
                conflicts.pop(tag, None)
            elif precedence == existing[:2]:
                if value == existing[2]:
                    existing[3].add(rule.id)
                else:
                    existing[3].add(rule.id)
                    conflicts[tag] = RuleConflict(
                        tag=tag,
                        priority=rule.priority,
                        rule_ids=tuple(sorted(existing[3])),
                    )
    if conflicts:
        return RuleResolution(None, tuple(conflicts.values()))
    if not selected:
        return RuleResolution(None, ())
    metadata = {tag: value for tag, (_, _, value, _) in selected.items()}
    rule_ids = sorted(
        rule_id
        for _, _, _, matching_ids in selected.values()
        for rule_id in matching_ids
    )
    return RuleResolution(
        EffectiveRule(",".join(dict.fromkeys(rule_ids)), metadata), ()
    )


class EventNormalizer:
    """Translate watchdog events into candidate file paths."""

    def path_for(self, event: FileSystemEvent) -> Path | None:
        """Return a candidate for created, modified, or moved file events.

        :param event: Watchdog event received by an observer callback.
        :return: Canonical candidate path, or ``None`` for ignored events.
        """
        if event.is_directory:
            return None
        event_type = getattr(event, "event_type", "")
        if event_type == "moved":
            return Path(event.dest_path)
        if event_type in {"created", "modified", "closed"}:
            return Path(event.src_path)
        return None


class DebounceQueue:
    """A keyed, time-based queue that coalesces repeated path events."""

    def __init__(self, delay: float = 0.25) -> None:
        """Initialize the queue.

        :param delay: Quiet period in seconds before dispatch.
        """
        self.delay = delay
        self._items: dict[Path, float] = {}
        self._lock = threading.Lock()

    def put(self, path: Path) -> None:
        """Add or refresh one path's quiet-period deadline.

        :param path: Candidate path to coalesce.
        """
        with self._lock:
            self._items[path.resolve()] = time.monotonic() + self.delay

    def pop_ready(self) -> list[Path]:
        """Remove and return paths whose quiet period elapsed.

        :return: Ready canonical paths.
        """
        now = time.monotonic()
        with self._lock:
            ready = [path for path, deadline in self._items.items() if deadline <= now]
            for path in ready:
                del self._items[path]
        return ready


class FileStabilityProbe:
    """Require consecutive unchanged size/mtime observations before processing."""

    def __init__(self, settle_seconds: float = 0.5) -> None:
        """Initialize a file stability probe.

        :param settle_seconds: How long the file must remain unchanged to pass.
        """
        self.settle_seconds = settle_seconds
        self._seen: dict[Path, tuple[int, int, float]] = {}

    def ready(self, path: Path) -> bool:
        """Report whether the current file state has settled.

        Records the first observation of each size/mtime state and only reports
        ready once that state has persisted unchanged for ``settle_seconds``.
        Probing an already-stable file repeatedly therefore converges instead of
        restarting the settle window on every call.

        :param path: Existing file to inspect.
        :return: Whether the file has been unchanged for the settle period.
        """
        key = path.resolve()
        try:
            stat = path.stat()
        except OSError:
            self._seen.pop(key, None)
            return False
        state = (stat.st_size, stat.st_mtime_ns)
        now = time.monotonic()
        previous = self._seen.get(key)
        # A changed state (or a fresh file) starts a new settle window.
        if previous is None or previous[:2] != state:
            self._seen[key] = (*state, now)
            return False
        return now - previous[2] >= self.settle_seconds

    def forget(self, path: Path) -> None:
        """Discard settled-state tracking for a completed path.

        :param path: Path whose state should no longer be retained.
        """
        self._seen.pop(path.resolve(), None)

    def clear(self) -> None:
        """Discard all state, such as after a rule-set reload."""
        self._seen.clear()


class MetadataReconciler:
    """Idempotently reconcile metadata without allowing media errors to escape."""

    def __init__(
        self, music_file_factory: Callable[[Path], object] = MusicFile
    ) -> None:
        """Initialize a reconciler.

        :param music_file_factory: Injectable music file constructor.
        """
        self.music_file_factory = music_file_factory

    def reconcile(self, path: Path, rule: WatchRule | EffectiveRule) -> bool:
        """Update only mismatched metadata and contain all per-file failures.

        :param path: File path to reconcile.
        :param rule: Desired metadata rule.
        :return: Whether metadata was saved.
        """
        try:
            media = self.music_file_factory(path)
            changed = False
            for name, desired in rule.metadata.items():
                tag = Tags(name)
                desired_value = (
                    [str(item) for item in desired]
                    if isinstance(desired, list)
                    else str(desired)
                )
                if media[tag] != desired_value:
                    media[tag] = desired_value
                    changed = True
            if changed:
                media.save()
            return changed
        except Exception:
            LOGGER.exception("Could not reconcile %s for rule %s", path, rule.id)
            return False


class _QueueingHandler(FileSystemEventHandler):
    """Keep observer callbacks limited to normalizing and enqueuing events."""

    def __init__(self, callback: Callable[[FileSystemEvent], None]) -> None:
        """Initialize a forwarding handler.

        :param callback: Fast callback invoked for every filesystem event.
        """
        self.callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Forward a watchdog event without doing metadata work.

        :param event: Event emitted by watchdog.
        """
        self.callback(event)


class _DaemonWorkerPool:
    """Run bounded reconciliation work without making shutdown unbounded."""

    def __init__(self, workers: int) -> None:
        """Start daemon workers that consume submitted callbacks.

        :param workers: Maximum number of active worker threads.
        :raises ValueError: If workers is not positive.
        """
        if workers < 1:
            raise ValueError("Watch service requires at least one worker.")
        self._tasks: queue.Queue[tuple[Callable[[Path], None], Path] | None] = (
            queue.Queue()
        )
        self._accepting = True
        self._closed = False
        self._lock = threading.Lock()
        self._threads = [
            threading.Thread(
                target=self._run, daemon=True, name=f"autometa-watch-{index}"
            )
            for index in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    def _run(self) -> None:
        """Execute queued work until shutdown sends a sentinel."""
        while True:
            task = self._tasks.get()
            try:
                if task is None:
                    return
                callback, path = task
                callback(path)
            finally:
                self._tasks.task_done()

    def submit(self, callback: Callable[[Path], None], path: Path) -> bool:
        """Queue one work item unless shutdown has started.

        :param callback: Worker callback.
        :param path: Path to pass to the callback.
        :return: Whether the task was accepted.
        """
        with self._lock:
            if not self._accepting:
                return False
            self._tasks.put((callback, path))
            return True

    def shutdown(self, timeout: float) -> None:
        """Cancel queued work and wait only up to the caller's deadline.

        Running callbacks cannot be force-cancelled safely. Workers are daemon
        threads so a blocked callback cannot keep the foreground service process
        alive after the configured shutdown deadline.

        :param timeout: Maximum seconds to wait for workers to exit.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._accepting = False
            # Drop not-yet-started work before placing termination sentinels.
            while True:
                try:
                    self._tasks.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._tasks.task_done()
            for _ in self._threads:
                self._tasks.put(None)
        deadline = time.monotonic() + max(timeout, 0)
        for thread in self._threads:
            thread.join(timeout=max(deadline - time.monotonic(), 0))


class WatchService:
    """Run all configured rules in one supervised foreground service."""

    def __init__(
        self,
        store: RuleStore,
        *,
        observer_factory: Callable[[], Observer] | None = None,
        observer_mode: str = "auto",
        reconciler: MetadataReconciler | None = None,
        workers: int = 2,
        debounce_delay: float = 0.25,
        shutdown_timeout: float = 5.0,
    ) -> None:
        """Initialize service dependencies.

        :param store: Persistent declarative rule store.
        :param observer_factory: Optional injectable watchdog observer constructor.
        :param observer_mode: ``auto``, ``native``, or ``polling`` selection.
        :param reconciler: Injectable metadata reconciliation component.
        :param workers: Maximum concurrent file workers.
        :param debounce_delay: Event quiet period.
        :param shutdown_timeout: Maximum work-drain time on shutdown.
        """
        self.store = store
        self.observer_factory = observer_factory
        self.observer_mode = observer_mode
        self.reconciler = reconciler or MetadataReconciler()
        self.workers = workers
        self.queue = DebounceQueue(debounce_delay)
        self.probe = FileStabilityProbe()
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_event = threading.Event()
        self._observer: Observer | None = None
        self._rules: list[WatchRule] = []
        self._inflight: set[Path] = set()
        self._dirty_paths: set[Path] = set()
        self._inflight_lock = threading.Lock()

    def request_shutdown(self, *_: object) -> None:
        """Set the shutdown event without performing lifecycle work in a signal handler.

        :param _: Ignored signal callback values.
        """
        self.shutdown_event.set()

    def _enqueue_event(self, event: FileSystemEvent) -> None:
        """Normalize a callback event and enqueue matching candidates.

        :param event: Raw watchdog event.
        """
        path = EventNormalizer().path_for(event)
        if path is not None and any(
            PathMatcher(rule).matches(path) for rule in self._rules
        ):
            self.queue.put(path)

    def _schedule(self) -> None:
        """Create and start an observer for the current set of rules."""
        factory = self.observer_factory or select_observer_factory(
            (Path(rule.root) for rule in self._rules),
            observer_mode=self.observer_mode,
        )
        observer = factory()
        handler = _QueueingHandler(self._enqueue_event)
        for rule in self._rules:
            observer.schedule(handler, rule.root, recursive=rule.recursive)
        observer.start()
        self._observer = observer

    def _initial_scan(self) -> None:
        """Enqueue all existing matching files before relying on events."""
        for rule in self._rules:
            root = Path(rule.root)
            iterator: Iterable[Path] = (
                root.rglob("*") if rule.recursive else root.glob("*")
            )
            for path in iterator:
                if path.is_file() and PathMatcher(rule).matches(path):
                    self.queue.put(path)

    def _process(self, path: Path) -> None:
        """Reconcile the effective metadata target for a settled path.

        :param path: Candidate file path.
        """
        settled = False
        try:
            if not self.probe.ready(path):
                if not self.shutdown_event.is_set():
                    self.queue.put(path)
                return
            settled = True
            resolution = resolve_effective_rule(path, self._rules)
            if resolution.conflicts:
                for conflict in resolution.conflicts:
                    LOGGER.error(
                        "Conflicting watch rules for %s: tag %s has incompatible "
                        "values at priority %s (rules: %s); skipping file.",
                        path,
                        conflict.tag,
                        conflict.priority,
                        ", ".join(conflict.rule_ids),
                    )
                return
            if resolution.rule is not None:
                self.reconciler.reconcile(path, resolution.rule)
        except Exception:
            LOGGER.exception("Unexpected worker failure for %s", path)
        finally:
            if settled:
                self.probe.forget(path)
            requeue = False
            with self._inflight_lock:
                self._inflight.discard(path)
                if path in self._dirty_paths:
                    self._dirty_paths.discard(path)
                    requeue = not self.shutdown_event.is_set()
            if requeue:
                self.queue.put(path)

    def _dispatch_ready(self, executor: _DaemonWorkerPool) -> None:
        """Submit ready, non-duplicate paths to the bounded worker pool.

        A fresh event for a path currently being reconciled is remembered and
        produces one follow-up pass once the active work completes.

        :param executor: Worker pool.
        """
        for path in self.queue.pop_ready():
            with self._inflight_lock:
                if path in self._inflight:
                    self._dirty_paths.add(path)
                    continue
                self._inflight.add(path)
            if not executor.submit(self._process, path):
                with self._inflight_lock:
                    self._inflight.discard(path)

    def run(self) -> int:
        """Run until shutdown, observer death, or singleton acquisition failure.

        :return: Zero on clean shutdown and nonzero on service failure.
        """
        try:
            singleton = acquire_service_lock(self.store.path)
            singleton.__enter__()
        except BlockingIOError:
            LOGGER.error("Another autometa watch service is already running.")
            return 1
        try:
            # Install graceful signal handlers only in the main thread, where
            # signal.signal is supported. Signal handlers only trip the shutdown
            # event; all teardown happens in normal control flow below.
            if threading.current_thread() is threading.main_thread():
                current = {
                    signum: signal.getsignal(signum)
                    for signum in (signal.SIGTERM, signal.SIGINT)
                }
                signal.signal(signal.SIGTERM, self.request_shutdown)
                signal.signal(signal.SIGINT, self.request_shutdown)
            else:
                current = {}
        except (ValueError, TypeError):
            current = {}
        try:
            self._rules = self.store.load()
            self._schedule()
            self._initial_scan()
            pool = _DaemonWorkerPool(self.workers)
            try:
                while not self.shutdown_event.wait(0.05):
                    if self._observer is None or not self._observer.is_alive():
                        LOGGER.error("Watch observer stopped unexpectedly.")
                        return 1
                    if self.store.changed():
                        self._observer.stop()
                        self._observer.join()
                        self._rules = self.store.reload()
                        self.probe.clear()
                        self._schedule()
                        self._initial_scan()
                    self._dispatch_ready(pool)
                if self._observer is not None:
                    self._observer.stop()
                    self._observer.join()
                deadline = time.monotonic() + self.shutdown_timeout
                while self._inflight and time.monotonic() < deadline:
                    time.sleep(0.01)
                pool.shutdown(timeout=max(deadline - time.monotonic(), 0))
            finally:
                pool.shutdown(timeout=0)
            return 0
        except Exception:
            LOGGER.exception("Watch service failed")
            return 1
        finally:
            for signum, old in current.items():
                signal.signal(signum, old)
            if self._observer is not None:
                with contextlib.suppress(Exception):
                    self._observer.stop()
                    self._observer.join()
            singleton.__exit__(None, None, None)


@contextlib.contextmanager
def acquire_service_lock(store_path: Path):
    """Acquire the nonblocking singleton lock derived from store identity.

    :param store_path: Path to the backing declarative store.
    :yields: Open lock file.
    :raises BlockingIOError: If another service owns this store's lock.
    """
    path = (
        Path(store_path).resolve().with_name(f".{Path(store_path).name}.service.lock")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        if signal is None:  # pragma: no cover - module import guard
            raise RuntimeError("Signal support unavailable")
        if __import__("os").name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BlockingIOError from exc
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield handle
        finally:
            if __import__("os").name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
