import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterable
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    LoggingEventHandler,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
    FileModifiedEvent,
    FileCreatedEvent,
    FileSystemEvent,
)
from watchdog.events import PatternMatchingEventHandler

from autometa.tags import Tags
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.config import ConfigRule

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
            if current_value != desired_value:
                LOGGER.info(
                    f"Updating {tag.value} in {file_path}: "
                    f"{current_value!r} -> {desired_value!r}"
                )
                music_file[tag] = desired_value
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
        patterns=[rule.pattern],
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
