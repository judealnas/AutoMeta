"""Foreground filesystem reconciliation service for declarative watch rules."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatch
import contextlib
import logging
from pathlib import Path
import signal
import threading
import time
from typing import Callable, Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from autometa.core import MusicFile
from autometa.tags import Tags
from autometa.watch_store import RuleStore, WatchRule

LOGGER = logging.getLogger(__name__)


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

        :param settle_seconds: Minimum delay between stable observations.
        """
        self.settle_seconds = settle_seconds
        self._seen: dict[Path, tuple[int, int, float]] = {}

    def ready(self, path: Path) -> bool:
        """Report whether the current file state has settled.

        :param path: Existing file to inspect.
        :return: Whether two observations are unchanged and sufficiently apart.
        """
        try:
            stat = path.stat()
        except OSError:
            return False
        key = path.resolve()
        state = (stat.st_size, stat.st_mtime_ns)
        previous = self._seen.get(key)
        now = time.monotonic()
        self._seen[key] = (*state, now)
        return (
            previous is not None
            and previous[:2] == state
            and now - previous[2] >= self.settle_seconds
        )


class MetadataReconciler:
    """Idempotently reconcile metadata without allowing media errors to escape."""

    def __init__(
        self, music_file_factory: Callable[[Path], object] = MusicFile
    ) -> None:
        """Initialize a reconciler.

        :param music_file_factory: Injectable music file constructor.
        """
        self.music_file_factory = music_file_factory

    def reconcile(self, path: Path, rule: WatchRule) -> bool:
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


class WatchService:
    """Run all configured rules in one supervised foreground service."""

    def __init__(
        self,
        store: RuleStore,
        *,
        observer_factory: Callable[[], Observer] = Observer,
        reconciler: MetadataReconciler | None = None,
        workers: int = 2,
        debounce_delay: float = 0.25,
        shutdown_timeout: float = 5.0,
    ) -> None:
        """Initialize service dependencies.

        :param store: Persistent declarative rule store.
        :param observer_factory: Injectable watchdog observer constructor.
        :param reconciler: Injectable metadata reconciliation component.
        :param workers: Maximum concurrent file workers.
        :param debounce_delay: Event quiet period.
        :param shutdown_timeout: Maximum work-drain time on shutdown.
        """
        self.store = store
        self.observer_factory = observer_factory
        self.reconciler = reconciler or MetadataReconciler()
        self.workers = workers
        self.queue = DebounceQueue(debounce_delay)
        self.probe = FileStabilityProbe()
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_event = threading.Event()
        self._observer: Observer | None = None
        self._rules: list[WatchRule] = []
        self._inflight: set[Path] = set()
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
        observer = self.observer_factory()
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
        """Reconcile every matching rule for a settled path with bounded retry.

        :param path: Candidate file path.
        """
        try:
            if not self.probe.ready(path):
                self.queue.put(path)
                return
            for rule in self._rules:
                if PathMatcher(rule).matches(path):
                    self.reconciler.reconcile(path, rule)
        except Exception:
            LOGGER.exception("Unexpected worker failure for %s", path)
        finally:
            with self._inflight_lock:
                self._inflight.discard(path)

    def _dispatch_ready(self, executor: ThreadPoolExecutor) -> None:
        """Submit ready, non-duplicate paths to the bounded worker pool.

        :param executor: Worker executor.
        """
        for path in self.queue.pop_ready():
            with self._inflight_lock:
                if path in self._inflight:
                    continue
                self._inflight.add(path)
            executor.submit(self._process, path)

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
            self._rules = self.store.load()
            self._schedule()
            self._initial_scan()
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                while not self.shutdown_event.wait(0.05):
                    if self._observer is None or not self._observer.is_alive():
                        LOGGER.error("Watch observer stopped unexpectedly.")
                        return 1
                    if self.store.changed():
                        self._observer.stop()
                        self._observer.join()
                        self._rules = self.store.reload()
                        self._schedule()
                        self._initial_scan()
                    self._dispatch_ready(executor)
                if self._observer is not None:
                    self._observer.stop()
                    self._observer.join()
                deadline = time.monotonic() + self.shutdown_timeout
                while self._inflight and time.monotonic() < deadline:
                    time.sleep(0.01)
            return 0
        except Exception:
            LOGGER.exception("Watch service failed")
            return 1
        finally:
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
