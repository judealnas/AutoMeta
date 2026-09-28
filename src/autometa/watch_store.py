"""Declarative YAML persistence and validation for the watch service."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Callable
import uuid

import yaml

from autometa.tags import Tags

ENV_STORE_PATH = "AUTOMETA_WATCH_STORE"


def get_watch_store_path() -> Path:
    """Return the configured platform-appropriate watch store path.

    :return: YAML store path.
    """
    if override := os.getenv(ENV_STORE_PATH):
        return Path(override).expanduser()
    if appdata := os.getenv("APPDATA"):
        return Path(appdata) / "autometa" / "watchers.yaml"
    return (
        Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "autometa"
        / "watchers.yaml"
    )


def normalize_metadata(
    metadata: dict[Tags, str | list[str] | int],
) -> dict[str, str | list[str]]:
    """Normalize CLI tag values for persistence.

    :param metadata: Enum-keyed metadata values.
    :return: String-keyed normalized values.
    """
    normalized: dict[str, str | list[str]] = {}
    for tag, value in metadata.items():
        if value is None:
            continue
        if tag == Tags.ARTIST:
            values = value.split(",") if isinstance(value, str) else value
            normalized[tag.value] = [
                str(item).strip() for item in values if str(item).strip()
            ]
        elif isinstance(value, list):
            normalized[tag.value] = [str(item) for item in value]
        else:
            normalized[tag.value] = str(value)
    return normalized


@dataclass(frozen=True)
class WatchRule:
    """Validated declarative definition of one metadata watch rule."""

    id: str
    root: str
    include: list[str]
    exclude: list[str]
    recursive: bool
    metadata: dict[str, str | list[str]]

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        metadata: dict[str, str | list[str]],
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        recursive: bool = False,
        id: str | None = None,
    ) -> "WatchRule":
        """Create a fully validated rule.

        :param root: Existing directory to watch.
        :param metadata: Nonempty desired known tag mapping.
        :param include: Filename include patterns.
        :param exclude: Filename exclusion patterns.
        :param recursive: Whether descendants are watched.
        :param id: UUID string, generated when omitted.
        :return: Validated watch rule.
        :raises ValueError: If a field is invalid.
        """
        resolved = Path(root).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Watch root must be an existing directory: {root}")
        if not metadata:
            raise ValueError("Watch rule metadata must not be empty.")
        cleaned: dict[str, str | list[str]] = {}
        for key, value in metadata.items():
            try:
                Tags(key)
            except ValueError as exc:
                raise ValueError(f"Unknown metadata tag: {key}") from exc
            if isinstance(value, list):
                if not value:
                    raise ValueError("Watch rule metadata values must not be empty.")
                cleaned[key] = [str(item) for item in value]
            elif value is not None and str(value):
                cleaned[key] = str(value)
            else:
                raise ValueError("Watch rule metadata values must not be empty.")
        return cls(
            str(uuid.UUID(id)) if id else str(uuid.uuid4()),
            str(resolved),
            ["*"] if include is None else list(include),
            [] if exclude is None else list(exclude),
            recursive,
            cleaned,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize this rule for the YAML schema.

        :return: Serializable mapping.
        """
        return {
            "id": self.id,
            "root": self.root,
            "include": self.include,
            "exclude": self.exclude,
            "recursive": self.recursive,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "WatchRule":
        """Deserialize one validated YAML rule.

        :param value: Raw rule mapping.
        :return: Validated rule.
        :raises TypeError: If metadata is malformed.
        """
        metadata = value.get("metadata")
        if not isinstance(metadata, dict):
            raise TypeError("Watch rule metadata must be a mapping.")
        return cls.create(
            id=str(value["id"]),
            root=Path(str(value["root"])),
            include=[str(item) for item in value.get("include", ["*"])],
            exclude=[str(item) for item in value.get("exclude", [])],
            recursive=bool(value.get("recursive", False)),
            metadata={str(key): item for key, item in metadata.items()},
        )


class RuleStore:
    """Atomically manage the YAML document shared by CLI and service."""

    version = 2

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the store.

        :param path: Explicit store path or configured default.
        """
        self.path = Path(path) if path is not None else get_watch_store_path()
        self._signature = self._read_signature()

    @property
    def lock_path(self) -> Path:
        """Return the cross-process read-modify-write lock path.

        :return: Advisory lock path.
        """
        return self.path.with_name(f".{self.path.name}.lock")

    @contextlib.contextmanager
    def _locked(self):
        """Acquire a store-level advisory lock.

        :yields: None.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_signature(self) -> tuple[int, int] | None:
        """Return an mtime/size signature for reload detection.

        :return: Store signature or ``None`` when absent.
        """
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _load_unlocked(self) -> list[WatchRule]:
        """Load and validate rules without taking the RMW lock.

        :return: Validated rules.
        :raises TypeError: If YAML schema is malformed.
        :raises ValueError: If schema version or IDs are invalid.
        """
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise TypeError("Watch store must be a mapping.")
        if payload.get("version", self.version) != self.version:
            raise ValueError("Unsupported watch store version.")
        entries = payload.get("rules", [])
        if not isinstance(entries, list):
            raise TypeError("Watch store 'rules' must be a list.")
        if not all(isinstance(item, dict) for item in entries):
            raise TypeError("Watch store rule must be a mapping.")
        rules = [WatchRule.from_dict(item) for item in entries]
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError("Duplicate watch rule IDs.")
        return rules

    def _fsync_directory(self, directory: Path) -> None:
        """Persist a completed atomic rename on POSIX filesystems.

        :param directory: Directory containing the replaced store file.
        """
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _save_unlocked(self, rules: list[WatchRule]) -> None:
        """Fsync a same-directory temporary YAML file and atomically replace store.

        :param rules: Complete rules list to persist.
        :raises ValueError: If UUID identifiers repeat.
        """
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError("Duplicate watch rule IDs.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "version": self.version,
                        "rules": [rule.to_dict() for rule in rules],
                    },
                    handle,
                    sort_keys=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._fsync_directory(self.path.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._signature = self._read_signature()

    def load(self) -> list[WatchRule]:
        """Load current rules and establish reload baseline.

        :return: Current rules.
        """
        rules = self._load_unlocked()
        self._signature = self._read_signature()
        return rules

    def reload(self) -> list[WatchRule]:
        """Reload after an external configuration change.

        :return: Reloaded rules.
        """
        return self.load()

    def changed(self) -> bool:
        """Report whether the YAML file changed since last load.

        :return: Whether service schedules need rebuilding.
        """
        return self._read_signature() != self._signature

    def add(self, rule: WatchRule) -> None:
        """Atomically append a new unique rule.

        :param rule: Rule to persist.
        :raises ValueError: If its ID already exists.
        """
        with self._locked():
            rules = self._load_unlocked()
            if any(item.id == rule.id for item in rules):
                raise ValueError(f"Duplicate watch rule ID: {rule.id}")
            self._save_unlocked([*rules, rule])

    def update(self, rule_id: str, transform: Callable[[WatchRule], WatchRule]) -> bool:
        """Atomically replace one existing rule using its current stored value.

        The transform runs while the store's read-modify-write lock is held, so
        concurrent CLI changes cannot overwrite unrelated fields from a stale
        snapshot.

        :param rule_id: UUID of the rule to replace.
        :param transform: Function that creates the validated replacement rule.
        :return: Whether an existing rule was updated.
        :raises ValueError: If the replacement changes the rule ID.
        """
        with self._locked():
            rules = self._load_unlocked()
            for index, existing in enumerate(rules):
                if existing.id != rule_id:
                    continue
                replacement = transform(existing)
                if replacement.id != rule_id:
                    raise ValueError("Updated watch rule ID must not change.")
                self._save_unlocked([*rules[:index], replacement, *rules[index + 1 :]])
                return True
            return False

    def remove(self, rule_id: str) -> bool:
        """Atomically delete a rule.

        :param rule_id: UUID of the rule to remove.
        :return: Whether a configured rule was removed.
        """
        with self._locked():
            rules = self._load_unlocked()
            remaining = [rule for rule in rules if rule.id != rule_id]
            if len(remaining) == len(rules):
                return False
            self._save_unlocked(remaining)
            return True
