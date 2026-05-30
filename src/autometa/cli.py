import argparse
import glob
import os
import pathlib
import signal
import subprocess
import sys
import time
import warnings

from autometa.tags import Tags
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.config import Config
from autometa.watch_store import (
    WatchSpec,
    get_watch_store_path,
    load_watch_store,
    normalize_metadata,
    normalize_watch_pattern,
    save_watch_store,
)


def add_metadata_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_append_artists: bool,
    include_comment: bool,
) -> None:
    parser.add_argument(
        f"--{Tags.ARTIST.lower()}",
        type=str,
        help="Comma-separated sequence of artist names.",
    )

    if include_append_artists:
        parser.add_argument(
            "--append-artists",
            action="store_true",
            help="Combine new artist names with existing instead of replacing.",
        )

    parser.add_argument(
        f"--{Tags.ALBUM.lower()}",
        type=str,
        help="Album name.",
    )
    parser.add_argument(
        f"--{Tags.TITLE.lower()}",
        type=str,
        help="Title of the track.",
    )
    parser.add_argument(
        f"--{Tags.TRACK.lower()}",
        type=int,
        help="Track number.",
    )
    parser.add_argument(
        f"--{Tags.YEAR.lower()}",
        type=int,
        help="Year of release.",
    )
    parser.add_argument(
        f"--{Tags.GENRE.lower()}",
        type=str,
        help="Genre of the track.",
    )
    if include_comment:
        parser.add_argument(
            f"--{Tags.COMMENT.lower()}",
            type=str,
            help="Comment.",
        )


PARSER = argparse.ArgumentParser(
    prog="autometa",
    description="Modify audio file metadata",
)
PARSER.add_argument("filespec", type=str, help="Files to modify.")

PARSER.add_argument(
    "--rulefile",
    type=pathlib.Path,
    help="File containing metadata rules.",
)

add_metadata_arguments(
    PARSER,
    include_append_artists=True,
    include_comment=False,
)

PARSER.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase verbosity.",
)

WATCH_ACTION_PARSER = argparse.ArgumentParser(
    prog="autometa watch",
    description="Manage configured metadata watchers.",
)
WATCH_ACTION_PARSER.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase verbosity.",
)
WATCH_ACTION_SUBPARSERS = WATCH_ACTION_PARSER.add_subparsers(
    dest="action",
    required=True,
)
WATCH_ACTION_SUBPARSERS.add_parser("list", help="List configured watchers.")
WATCH_START_PARSER = WATCH_ACTION_SUBPARSERS.add_parser(
    "start", help="Start a configured watcher."
)
WATCH_START_PARSER.add_argument("id", type=int, help="Watcher ID.")
WATCH_STOP_PARSER = WATCH_ACTION_SUBPARSERS.add_parser(
    "stop", help="Stop a running watcher."
)
WATCH_STOP_PARSER.add_argument("id", type=int, help="Watcher ID.")

WATCH_CONFIG_PARSER = argparse.ArgumentParser(
    prog="autometa watch",
    description="Configure a new metadata watcher.",
)
WATCH_CONFIG_PARSER.add_argument(
    "pattern",
    type=str,
    help="File pattern to watch.",
)
WATCH_CONFIG_PARSER.add_argument(
    "-s",
    "--save-only",
    action="store_true",
    help="Save watcher configuration without starting it.",
)
WATCH_CONFIG_PARSER.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase verbosity.",
)
add_metadata_arguments(
    WATCH_CONFIG_PARSER,
    include_append_artists=False,
    include_comment=True,
)


def setup_logging(verbosity: int):
    """Set up logging."""
    import logging

    # Set up logging
    verbosity_level_map = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=verbosity_level_map.get(verbosity, logging.DEBUG),
    )
    return logging.getLogger("autometa:cli")


def _collect_metadata_from_args(
    args: argparse.Namespace,
) -> dict[Tags, str | list[str] | int]:
    """Extract metadata arguments from command-line namespace.

    Iterates through all Tags enum values and collects any corresponding
    command-line arguments from the namespace.

    :param args: Parsed command-line arguments
    :return: Dictionary mapping Tags to their values
    """
    metadata: dict[Tags, str | list[str] | int] = {}
    for tag in Tags:
        value = getattr(args, tag.lower(), None)
        if value is not None:
            metadata[tag] = value
    return metadata


def _find_watch(watchers: list[WatchSpec], watch_id: int) -> WatchSpec | None:
    """Find a watcher by ID.

    :param watchers: List of WatchSpec objects to search
    :param watch_id: ID to search for
    :return: WatchSpec if found, None otherwise
    """
    return next((watch for watch in watchers if watch.id == watch_id), None)


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    Uses os.kill with signal 0 to check process existence in a cross-platform
    manner (works on Windows and Unix-like systems).

    :param pid: Process ID to check
    :return: True if process exists, False otherwise
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_process(pid: int) -> bool:
    """Attempt to terminate a process gracefully.

    Sends SIGTERM to the process and checks if it has stopped after a short
    delay. Returns True if the process is no longer running.

    :param pid: Process ID to terminate
    :return: True if process was terminated, False otherwise
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    time.sleep(0.2)
    return not _is_process_running(pid)


def _spawn_watch_process(watch_id: int, verbosity: int) -> int:
    """Spawn a background watcher process.

    Creates a detached subprocess that runs the watch_runner module. On Windows,
    uses DETACHED_PROCESS flag; on Unix, uses start_new_session to detach from
    the parent process group.

    :param watch_id: ID of the watcher to run
    :param verbosity: Verbosity level (0-2) for logging
    :return: Process ID of spawned watcher
    """
    cmd = [sys.executable, "-m", "autometa.watch_runner", str(watch_id)]
    if verbosity:
        cmd.insert(3, f"-{'v' * verbosity}")

    if os.name == "nt":
        creationflags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    else:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return process.pid


def _refresh_watch_statuses(watchers: list[WatchSpec]) -> None:
    """Update watcher statuses based on process availability.

    Checks if any running watchers still have active processes. Marks
    watchers as stopped if their PIDs no longer exist and persists changes
    to storage.

    :param watchers: List of WatchSpec objects to refresh
    """
    updated = False
    for watch in watchers:
        if watch.pid and not _is_process_running(watch.pid):
            watch.pid = None
            watch.status = "stopped"
            updated = True
    if updated:
        save_watch_store(watchers)


def _format_metadata(metadata: dict[str, str | list[str]]) -> str:
    """Format metadata dictionary as a compact string representation.

    Converts metadata key-value pairs to ``key=value`` format, joining list
    values with commas. Returns empty string if metadata is empty.

    :param metadata: Dictionary of metadata to format
    :return: Formatted metadata string
    """
    if not metadata:
        return ""
    parts = []
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, list):
            value_text = ",".join(value)
        else:
            value_text = str(value)
        parts.append(f"{key}={value_text}")
    return ", ".join(parts)


def _format_watch_table(watchers: list[WatchSpec]) -> str:
    """Format watcher list as a formatted ASCII table.

    Creates a table with columns for ID, Status, Pattern, and Metadata.
    Automatically sizes columns to fit content.

    :param watchers: List of WatchSpec objects to display
    :return: Formatted table string
    """
    headers = ["ID", "Status", "Pattern", "Metadata"]
    rows = [
        [str(watch.id), watch.status, watch.pattern, _format_metadata(watch.metadata)]
        for watch in watchers
    ]
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in rows))
        if rows
        else len(headers[idx])
        for idx in range(len(headers))
    ]
    header_line = (
        "| "
        + " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))
        + " |"
    )
    separator = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    row_lines = [
        "| "
        + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers)))
        + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator, *row_lines])


def _handle_watch_command(argv: list[str]) -> None:
    """Handle all watch subcommands (list, start, stop, configure).

    Dispatches to appropriate handlers based on the first argument:
    - ``list``: Display all configured watchers
    - ``start <id>``: Start a stopped watcher
    - ``stop <id>``: Stop a running watcher
    - ``<pattern> [--metadata]``: Configure a new watcher

    :param argv: Command-line arguments after 'watch'
    """
    if not argv:
        WATCH_CONFIG_PARSER.print_help()
        return

    if argv[0] in {"list", "start", "stop"}:
        parsed = WATCH_ACTION_PARSER.parse_args(argv)
        logger = setup_logging(parsed.verbose)
        watchers = load_watch_store()
        _refresh_watch_statuses(watchers)

        if parsed.action == "list":
            if not watchers:
                logger.info("No watchers configured. Store: %s", get_watch_store_path())
                print(_format_watch_table([]))
                return
            print(_format_watch_table(watchers))
            return

        watch = _find_watch(watchers, parsed.id)
        if watch is None:
            logger.error("Watcher %s not found.", parsed.id)
            return

        if parsed.action == "start":
            if watch.pid and _is_process_running(watch.pid):
                logger.info(
                    "Watcher %s is already running (pid=%s).", watch.id, watch.pid
                )
                return

            watch_root = pathlib.Path(watch.watch_root)
            if not watch_root.exists():
                logger.error("Watch root does not exist: %s", watch_root)
                return

            pid = _spawn_watch_process(watch.id, parsed.verbose)
            watch.pid = pid
            watch.status = "running"
            save_watch_store(watchers)
            logger.info("Watcher %s started (pid=%s).", watch.id, pid)
            return

        if parsed.action == "stop":
            if not watch.pid:
                watch.status = "stopped"
                save_watch_store(watchers)
                logger.warning("Watcher %s is not running.", watch.id)
                return

            if not _is_process_running(watch.pid):
                watch.pid = None
                watch.status = "stopped"
                save_watch_store(watchers)
                logger.warning("Watcher %s is not running.", watch.id)
                return

            if _terminate_process(watch.pid):
                watch.pid = None
                watch.status = "stopped"
                save_watch_store(watchers)
                logger.info("Watcher %s stopped.", watch.id)
            else:
                logger.error("Failed to stop watcher %s (pid=%s).", watch.id, watch.pid)
            return

    parsed = WATCH_CONFIG_PARSER.parse_args(argv)
    logger = setup_logging(parsed.verbose)
    raw_metadata = _collect_metadata_from_args(parsed)
    metadata = normalize_metadata(raw_metadata)
    if not metadata:
        logger.warning("No metadata provided for watcher.")

    default_root = pathlib.Path.cwd()
    watch_root, normalized_pattern = normalize_watch_pattern(
        parsed.pattern, default_root
    )

    watchers = load_watch_store()
    next_id = max((watch.id for watch in watchers), default=0) + 1
    watch = WatchSpec(
        id=next_id,
        pattern=normalized_pattern,
        metadata=metadata,
        watch_root=str(watch_root),
        status="stopped",
        pid=None,
    )
    watchers.append(watch)
    save_watch_store(watchers)
    logger.info("Watcher %s saved (root=%s).", watch.id, watch_root)

    if parsed.save_only:
        return

    pid = _spawn_watch_process(watch.id, parsed.verbose)
    watch.pid = pid
    watch.status = "running"
    save_watch_store(watchers)
    logger.info("Watcher %s started (pid=%s).", watch.id, pid)


def main(args: list[str] | None = None):
    # Get file
    # If no explicit args provided, use sys.argv[1:] so standard flags like
    # --help are handled by argparse. Otherwise, use the provided sequence.
    if args is None:
        args = sys.argv[1:]
    else:
        args = list(args)

    if args and args[0] == "watch":
        _handle_watch_command(args[1:])
        return

    args = PARSER.parse_args(args)
    LOGGER = setup_logging(args.verbose)
    append_artists: bool = args.append_artists

    # Load config if provided
    config: Config | None = None
    if args.rulefile:
        LOGGER.info("Loading rulefile: %s", args.rulefile)
        config = Config.load(args.rulefile)

    # Extract metadata from command-line arguments
    cli_metadata = {}
    for tag in Tags:
        value = getattr(args, tag.lower(), None)
        LOGGER.debug("Received %s: %s", tag, value)
        if value is not None:
            cli_metadata[tag] = value

    filepath = args.filespec
    files = glob.glob(str(filepath))
    LOGGER.debug("Globbed files: %s", files)

    for f in files:
        path = pathlib.Path(f)
        LOGGER.debug("Processing file: %s", path)

        try:
            file = MusicFile(path)
        except UnsupportedFileTypeError as e:
            filename = path.parts[-1]
            warnings.warn(f"Skipping unsupported file {filename}: {e}")
            LOGGER.warning("Skipping unsupported file %s: %s", filename, e)
            continue

        # Build metadata: config rules < CLI arguments
        metadata = {}
        if config:
            # Apply config rules for this file
            config_tags = config.get_tags_for_file(path)
            metadata.update(config_tags)
            LOGGER.debug("Config tags for %s: %s", path, config_tags)

        # Override with CLI arguments (higher priority)
        metadata.update(cli_metadata)
        LOGGER.debug("Final metadata for %s: %s", path, metadata)

        # Updating tags
        for tag, value in metadata.items():
            if value is not None:
                LOGGER.debug("Updating %s: %s", tag, value)
                if tag == Tags.ARTIST:
                    LOGGER.debug("Appending artists?: %s", append_artists)
                    # Handle both string (from CLI) and list (from config)
                    if isinstance(value, str):
                        artist_data = value.split(",")
                    else:
                        artist_data = value

                    if append_artists:
                        # Get existing artists
                        existing = file[Tags.ARTIST]
                        if existing:
                            # Combine with new artists
                            if isinstance(existing, list):
                                artist_data = existing + artist_data
                            else:
                                artist_data = [existing] + artist_data
                    file[Tags.ARTIST] = artist_data
                else:
                    file[tag] = str(value)

                LOGGER.debug("New %s: %s", tag, file[tag])

        # Save changes
        LOGGER.debug("Saving changes to %s", path)
        file.save()
