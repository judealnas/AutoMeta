import logging
from pathlib import Path
from typing import Iterable
from watchdog.observers import Observer
from watchdog.events import (
    LoggingEventHandler,
    FileModifiedEvent,
    FileCreatedEvent,
)
from watchdog.events import PatternMatchingEventHandler

from autometa.tags import Tags
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.config import Config, ConfigRule

LOGGER = logging.getLogger(__name__)


class MetadataEventHandler(PatternMatchingEventHandler):
    """Watches for file creation/modification and updates metadata.

    When a matching file is created or modified, this handler verifies
    that the file's metadata matches the desired tags. Any missing or
    incorrect metadata is automatically updated.
    """

    def __init__(
        self,
        patterns: list[str] | None = None,
        ignore_patterns: list[str] | None = None,
        ignore_directories: bool = True,
        case_sensitive: bool = False,
        desired_metadata: dict[Tags, str | list[str]] | None = None,
    ):
        """Initialize the MetadataEventHandler.

        Args:
            patterns: Glob patterns for files to match (e.g., ['*.mp3', '*.flac'])
            ignore_patterns: Glob patterns for files to ignore
            ignore_directories: Whether to ignore directory events
            case_sensitive: Whether pattern matching is case-sensitive
            desired_metadata: Dictionary mapping Tags to desired values
                (values may be a string or list of strings)
        """
        super().__init__(
            patterns=patterns or ["*"],
            ignore_patterns=ignore_patterns,
            ignore_directories=ignore_directories,
            case_sensitive=case_sensitive,
        )
        self.desired_metadata = desired_metadata or {}

    def _update_metadata(self, file_path: str) -> None:
        """Update metadata for a file if needed.

        Args:
            file_path: Path to the file to update
        """
        try:
            music_file = MusicFile(file_path)
        except UnsupportedFileTypeError as e:
            LOGGER.debug(f"Skipping unsupported file: {e}")
            return

        updated = False
        for tag, desired_value in self.desired_metadata.items():
            current_value = music_file[tag]
            normalized_desired = self._normalize_desired_value(desired_value)
            if not self._values_match(current_value, normalized_desired):
                LOGGER.info(
                    f"Updating {tag.value} in {file_path}: "
                    f"{current_value!r} -> {normalized_desired!r}"
                )
                music_file[tag] = normalized_desired
                updated = True

        if updated:
            music_file.save()
            LOGGER.info(f"Metadata saved for {file_path}")

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle file creation event."""
        if not event.is_directory:
            LOGGER.debug(f"File created: {event.src_path}")
            self._update_metadata(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification event."""
        if not event.is_directory:
            LOGGER.debug(f"File modified: {event.src_path}")
            self._update_metadata(event.src_path)

    @staticmethod
    def _normalize_desired_value(
        desired_value: str | list[str] | int,
    ) -> str | list[str]:
        """Normalize a desired metadata value to string or list of strings.

        Converts integer and other types to strings for consistent comparison
        with file metadata.

        :param desired_value: The metadata value to normalize
        :return: Normalized value as string or list of strings
        """
        if isinstance(desired_value, list):
            return [str(item) for item in desired_value]
        return str(desired_value)

    @staticmethod
    def _values_match(
        current_value: str | list[str] | None,
        desired_value: str | list[str],
    ) -> bool:
        """Check if current file metadata matches the desired value.

        Handles comparison of string and list values, including comma and
        semicolon-separated variants (for compatibility with tag formats).

        :param current_value: The current file metadata value
        :param desired_value: The desired metadata value
        :return: True if values match, False otherwise
        """
        if current_value is None:
            return False
        if isinstance(desired_value, list):
            if isinstance(current_value, list):
                return current_value == desired_value
            if isinstance(current_value, str):
                return current_value in (
                    "; ".join(desired_value),
                    ", ".join(desired_value),
                )
            return False
        if isinstance(current_value, list):
            return current_value == [desired_value]
        return current_value == desired_value


def build_metadata_observer(rule: ConfigRule) -> Observer:
    """Build an observer for a configuration rule.

    Creates an observer with a MetadataEventHandler and LoggingEventHandler
    configured for the rule's pattern and desired metadata tags.

    Args:
        rule: A ConfigRule specifying the file pattern and desired metadata tags

    Returns:
        An Observer configured with handlers but not yet started
    """
    observer = Observer()
    watch_root = rule.base_path or Path.cwd()

    # Create handlers
    metadata_handler = MetadataEventHandler(
        patterns=[_make_absolute_pattern(rule.pattern, watch_root)],
        desired_metadata=rule.tags,
    )
    logging_handler = LoggingEventHandler()

    # Schedule handlers on the observer
    observer.schedule(metadata_handler, path=str(watch_root), recursive=True)
    observer.schedule(logging_handler, path=str(watch_root), recursive=True)

    LOGGER.debug(
        "Built observer for rule pattern=%s, tags=%s, watch_root=%s",
        rule.pattern,
        rule.tags,
        watch_root,
    )

    return observer


def build_metadata_observer_for_watch(
    pattern: str,
    desired_metadata: dict[Tags, str | list[str]],
    *,
    watch_root: Path,
) -> Observer:
    """Build an observer for a configured file watcher.

    Creates an observer with a MetadataEventHandler and LoggingEventHandler
    configured for a watch specification. The pattern is resolved relative
    to the watch_root directory.

    :param pattern: Glob pattern for files to watch
    :param desired_metadata: Dictionary mapping Tags to metadata values
    :param watch_root: Root directory to watch
    :return: Configured Observer instance
    """
    observer = Observer()
    metadata_handler = MetadataEventHandler(
        patterns=[_make_absolute_pattern(pattern, watch_root)],
        desired_metadata=desired_metadata,
    )
    logging_handler = LoggingEventHandler()
    observer.schedule(metadata_handler, path=str(watch_root), recursive=True)
    observer.schedule(logging_handler, path=str(watch_root), recursive=True)
    return observer


def _make_absolute_pattern(pattern: str, watch_root: Path) -> str:
    """Convert a pattern to an absolute path.

    If the pattern is already absolute, returns it unchanged. Otherwise,
    resolves it relative to the watch_root directory.

    :param pattern: Pattern to resolve
    :param watch_root: Root directory to resolve relative patterns against
    :return: Absolute pattern string
    """
    pattern_path = Path(pattern)
    if pattern_path.is_absolute():
        return str(pattern_path)
    return str(watch_root / pattern_path)


def _is_watch_enabled(rule: ConfigRule, config: Config) -> bool:
    if rule.watch is not None:
        return rule.watch.enable
    if config.watch is not None:
        return config.watch.enable
    return False


def build_metadata_observers(config: Config) -> list[Observer]:
    """Build observers for all watch-enabled rules in a config."""
    observers: list[Observer] = []
    for rule in config.rules:
        if _is_watch_enabled(rule, config):
            observers.append(build_metadata_observer(rule))

    LOGGER.debug("Built %d observers from config", len(observers))
    return observers


def start_observers(observers: Iterable[Observer]) -> None:
    """Start all observers in order."""
    for observer in observers:
        observer.start()


def stop_observers(observers: Iterable[Observer]) -> None:
    """Stop and join all observers."""
    for observer in observers:
        observer.stop()
    for observer in observers:
        observer.join()
