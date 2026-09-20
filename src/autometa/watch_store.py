"""Manage persistent storage and configuration for file watchers.

This module handles loading, saving, and normalizing watcher configurations
stored in YAML format. It supports cross-platform paths for storing watcher
state and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import contextlib
import os
import yaml

from autometa.tags import Tags

STORE_VERSION = 1
ENV_STORE_PATH = "AUTOMETA_WATCH_STORE"
WILDCARD_CHARS = ("*", "?", "[")


@dataclass
class WatchSpec:
    """Specification for a file watcher.

    Represents a configured watcher that monitors files matching a pattern
    and applies metadata when those files are created or modified. This is a
    config-only record: runtime state (running/stopped, pid) is NOT stored
    here, but derived from the watcher's liveness lockfile.

    :ivar id: Unique identifier for this watcher
    :ivar pattern: Glob pattern for files to watch (relative to watch_root)
    :ivar metadata: Dictionary mapping metadata keys to values
    :ivar watch_root: Absolute path to the root directory being watched
    """

    id: int
    pattern: str
    metadata: dict[str, str | list[str]]
    watch_root: str

    def to_dict(self) -> dict[str, object]:
        """Convert watcher specification to dictionary for serialization.

        :return: Dictionary representation suitable for YAML serialization
        """
        return {
            "id": self.id,
            "pattern": self.pattern,
            "metadata": self.metadata,
            "watch_root": self.watch_root,
        }


def get_watch_store_path() -> Path:
    """Determine the platform-specific path for storing watcher configurations.

    Checks environment variables and platform conventions to find the appropriate
    config directory. Priority:

    1. ``AUTOMETA_WATCH_STORE`` environment variable (if set)
    2. ``%APPDATA%\\autometa\\watchers.yaml`` (Windows)
    3. ``$XDG_CONFIG_HOME/autometa/watchers.yaml`` (Linux/Unix with XDG)
    4. ``~/.config/autometa/watchers.yaml`` (default fallback)

    :return: Path object pointing to the watcher store file
    """
    override = os.getenv(ENV_STORE_PATH)
    if override:
        return Path(override).expanduser()

    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / ".autometa" / "watchers.yaml"

    xdg_config = os.getenv("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / ".autometa" / "watchers.yaml"

    return Path.home() / ".autometa" / "watchers.yaml"


def load_watch_store(path: Path | None = None) -> list[WatchSpec]:
    """Load all configured watchers from persistent storage.

    Reads the watcher configuration from the YAML store file. Creates an empty
    list if the store does not exist yet.

    :param path: Optional explicit path to the store file; defaults to the
        platform-resolved location (:func:`get_watch_store_path`)
    :return: List of WatchSpec objects
    :raises TypeError: If store format is invalid
    :raises ValueError: If store version is unsupported
    """
    path = Path(path) if path is not None else get_watch_store_path()
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise TypeError("Watch store must be a mapping.")

    version = data.get("version", STORE_VERSION)
    if version != STORE_VERSION:
        raise ValueError(f"Unsupported watch store version: {version}")

    items = data.get("watchers", [])
    if not isinstance(items, list):
        raise TypeError("Watch store 'watchers' must be a list.")

    watchers: list[WatchSpec] = []
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("Watch store entry must be a mapping.")

        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("Watch store entry metadata must be a mapping.")

        cleaned_metadata: dict[str, str | list[str]] = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                cleaned_metadata[str(key)] = value
            elif isinstance(value, list):
                cleaned_metadata[str(key)] = [str(item) for item in value]
            else:
                raise TypeError(
                    "Watch store metadata values must be strings or lists of strings."
                )

        watchers.append(
            WatchSpec(
                id=int(item["id"]),
                pattern=str(item["pattern"]),
                metadata=cleaned_metadata,
                watch_root=str(item["watch_root"]),
            )
        )

    return watchers


def save_watch_store(watchers: list[WatchSpec], path: Path | None = None) -> None:
    """Save watcher configurations to persistent storage.

    Creates the parent directory if it does not exist, then writes all
    watcher specifications to YAML format.

    :param watchers: List of WatchSpec objects to persist
    :param path: Optional explicit path to the store file; defaults to the
        platform-resolved location (:func:`get_watch_store_path`)
    """
    path = Path(path) if path is not None else get_watch_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STORE_VERSION,
        "watchers": [watcher.to_dict() for watcher in watchers],
    }
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def normalize_metadata(
    metadata: dict[Tags, str | list[str] | int],
) -> dict[str, str | list[str]]:
    """Convert metadata from Tags enum and mixed types to normalized string form.

    Handles type coercion and special cases:
    - Artist tags are split by comma and normalized to lists
    - All other values are converted to strings or lists of strings
    - None values are skipped

    :param metadata: Dictionary mapping Tags enum to values
    :return: Dictionary mapping tag names (strings) to normalized values
    """
    normalized: dict[str, str | list[str]] = {}
    for tag, value in metadata.items():
        if value is None:
            continue
        if tag == Tags.ARTIST:
            if isinstance(value, str):
                artists = [artist.strip() for artist in value.split(",")]
            else:
                artists = [str(artist).strip() for artist in value]
            normalized[tag.value] = [artist for artist in artists if artist]
            continue

        if isinstance(value, list):
            normalized[tag.value] = [str(item) for item in value]
        else:
            normalized[tag.value] = str(value)

    return normalized


def metadata_to_tags(
    metadata: dict[str, str | list[str]],
) -> dict[Tags, str | list[str]]:
    """Convert metadata from string keys to Tags enum.

    :param metadata: Dictionary mapping string tag names to values
    :return: Dictionary mapping Tags enum values to values
    :raises ValueError: If an unknown metadata tag is encountered
    """
    converted: dict[Tags, str | list[str]] = {}
    for key, value in metadata.items():
        try:
            tag = Tags(key)
        except ValueError as exc:
            raise ValueError(f"Unknown metadata tag: {key}") from exc
        converted[tag] = value
    return converted


def normalize_watch_pattern(pattern: str, default_root: Path) -> tuple[Path, str]:
    """Normalize a file watch pattern into base path and relative pattern.

    Splits an absolute or relative path pattern into a base directory and
    a watchdog-compatible pattern. Handles glob patterns by extracting the
    base path from the parts before any wildcards are encountered.

    :param pattern: File path or glob pattern to watch (may use ~ for home)
    :param default_root: Default base directory for relative patterns
    :return: Tuple of (resolved base path, relative pattern for watchdog)
    """
    pattern_path = Path(pattern).expanduser()
    parts = pattern_path.parts
    if not parts:
        return default_root, "*"

    wildcard_index = next(
        (
            idx
            for idx, part in enumerate(parts)
            if any(char in part for char in WILDCARD_CHARS)
        ),
        len(parts),
    )

    if wildcard_index == len(parts):
        base_parts = parts[:-1]
        remaining_parts = parts[-1:]
    else:
        base_parts = parts[:wildcard_index]
        remaining_parts = parts[wildcard_index:]

    if pattern_path.is_absolute():
        base_path = Path(*base_parts) if base_parts else Path(pattern_path.anchor)
    else:
        base_path = default_root / Path(*base_parts) if base_parts else default_root

    if not remaining_parts:
        remaining_parts = ["*"]

    normalized_pattern = str(Path(*remaining_parts))
    return base_path.resolve(strict=False), normalized_pattern


def liveness_lock_path(store_path: Path, watch_id: int) -> Path:
    """Return the path to a watcher's liveness lockfile.

    The lockfile is co-located with the watch store in the same directory and
    named ``<watch_id>.lock``.
    """
    return Path(store_path).with_name(f"{watch_id}.lock")


def _ensure_lock_file(lock_path: Path) -> None:
    """Create an empty lockfile if it does not exist.

    The file must exist and be at least one byte so that ``msvcrt.locking``
    (Windows) can operate on it; a NUL byte is written on first touch.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        lock_path.write_bytes(b"\0")


@contextlib.contextmanager
def acquire_liveness_lock(store_path: Path, watch_id: int, *, blocking: bool = True):
    """Acquire the per-watcher liveness lock.

    The runner holds this lock open for its entire lifetime as the liveness
    artifact for a watcher: while it is held, the watcher is "running". The OS
    releases the lock automatically when the holding process exits (including
    on crash/SIGKILL), so ``is_watch_running`` always reflects reality.

    On POSIX the lock is taken with ``fcntl.flock``; on Windows with
    ``msvcrt.locking`` (which requires a file of at least one byte, ensured
    here by :func:`_ensure_lock_file`).

    :param store_path: Path to the watch store file (lock is co-located)
    :param watch_id: ID of the watcher whose lock to take
    :param blocking: If False, raise ``BlockingIOError`` when already held
    :yields: The open lock file object, positioned at the start
    """
    lock_path = liveness_lock_path(store_path, watch_id)
    _ensure_lock_file(lock_path)
    # Open read/write (NOT append) so seek()+write() places bytes exactly.
    with open(lock_path, "r+b", buffering=0) as lock:
        if os.name == "nt":
            import msvcrt

            flag = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(lock.fileno(), flag, 1)
        else:
            import fcntl

            flag = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), flag)
        yield lock


def is_watch_running(store_path: Path, watch_id: int) -> tuple[bool, int | None]:
    """Report whether a watcher is currently running, based on its liveness lock.

    A watcher is "running" iff its liveness lock is held. When held, the PID
    recorded in the lockfile is the holder's PID (written by the live runner)
    and is therefore authoritative. When the lock is free, returns pid=None.

    :param store_path: Path to the watch store file (lock is co-located)
    :param watch_id: ID of the watcher to check
    :return: A tuple (running, pid) where pid is the holder's PID, or None
    """
    lock_path = liveness_lock_path(store_path, watch_id)
    if not lock_path.exists():
        return False, None

    try:
        lock = open(lock_path, "r+b", buffering=0)
    except OSError:
        return False, None

    with lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    pass  # lock is held
                else:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    return False, None
            else:
                import fcntl

                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass  # lock is held
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                    return False, None
        except OSError:
            return False, None

        # Lock is held - read the holder's PID from the file
        lock.seek(0)
        data = lock.read().decode().strip("\x00").strip()
        try:
            pid = int(data) if data else None
        except ValueError:
            pid = None
        return True, pid
