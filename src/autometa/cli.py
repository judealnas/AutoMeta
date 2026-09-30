"""Command-line interface for metadata updates and the watch service."""

from __future__ import annotations

import argparse
import glob
from pathlib import Path
import sys
import warnings

from autometa.config import Config
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.logging_util import setup_logging
from autometa.service_manager import ServiceManagerError, WatchServiceManager
from autometa.tags import Tags
from autometa.watch_logging import get_watch_log_path, setup_watch_logging
from autometa.watch_store import (
    RuleStore,
    WatchRule,
    get_watch_store_path,
    normalize_metadata,
)
from autometa.watcher import WatchService


def add_metadata_arguments(
    parser: argparse.ArgumentParser, *, include_append_artists: bool
) -> None:
    """Add supported metadata flags to an argparse parser.

    :param parser: Parser receiving metadata options.
    :param include_append_artists: Whether normal CLI append behavior is enabled.
    """
    parser.add_argument("--artist", type=str, help="Comma-separated artist names.")
    parser.add_argument("--album", type=str, help="Album name.")
    parser.add_argument("--title", type=str, help="Track title.")
    parser.add_argument("--track", type=int, help="Track number.")
    parser.add_argument("--year", type=int, help="Release year.")
    parser.add_argument("--genre", type=str, help="Genre.")
    parser.add_argument("--comment", type=str, help="Comment.")
    if include_append_artists:
        parser.add_argument(
            "--append-artists", action="store_true", help="Append artists."
        )


PARSER = argparse.ArgumentParser(
    prog="autometa", description="Modify audio file metadata"
)
PARSER.add_argument("filespec", type=str, help="Files to modify.")
PARSER.add_argument("--rulefile", type=Path, help="File containing metadata rules.")
PARSER.add_argument(
    "-v", "--verbose", action="count", default=0, help="Increase verbosity."
)
add_metadata_arguments(PARSER, include_append_artists=True)

WATCH_PARSER = argparse.ArgumentParser(
    prog="autometa watch", description="Manage metadata watch rules."
)
WATCH_SUBPARSERS = WATCH_PARSER.add_subparsers(dest="action", required=True)
WATCH_ADD = WATCH_SUBPARSERS.add_parser("add", help="Add a declarative watch rule.")
WATCH_ADD.add_argument("root", type=Path, help="Existing root directory to monitor.")
WATCH_ADD.add_argument(
    "--include",
    action="append",
    default=[],
    metavar="PATTERN",
    help="Root-relative '/'-separated path pattern; repeatable.",
)
WATCH_ADD.add_argument(
    "--exclude",
    action="append",
    default=[],
    metavar="PATTERN",
    help="Exclude filename pattern; repeatable.",
)
WATCH_ADD.add_argument(
    "--priority",
    type=int,
    default=0,
    help="Metadata precedence when rules overlap (default: 0).",
)
add_metadata_arguments(WATCH_ADD, include_append_artists=False)
WATCH_SUBPARSERS.add_parser("list", help="List configured watch rules.")
WATCH_REMOVE = WATCH_SUBPARSERS.add_parser(
    "remove", help="Remove a configured watch rule."
)
WATCH_REMOVE.add_argument("id", help="Watch rule UUID.")
WATCH_UPDATE = WATCH_SUBPARSERS.add_parser(
    "update", help="Update one configured watch rule."
)
WATCH_UPDATE.add_argument("id", help="Watch rule UUID.")
WATCH_UPDATE.add_argument(
    "--root", type=Path, help="Replacement existing root directory."
)
WATCH_UPDATE.add_argument(
    "--priority", type=int, default=None, help="Replacement metadata precedence."
)
WATCH_UPDATE_INCLUDE = WATCH_UPDATE.add_mutually_exclusive_group()
WATCH_UPDATE_INCLUDE.add_argument(
    "--include",
    action="append",
    default=None,
    metavar="PATTERN",
    help="Replace include patterns; repeatable.",
)
WATCH_UPDATE_INCLUDE.add_argument(
    "--clear-include",
    action="store_true",
    help="Clear include patterns, disabling matches until patterns are added.",
)
WATCH_UPDATE_EXCLUDE = WATCH_UPDATE.add_mutually_exclusive_group()
WATCH_UPDATE_EXCLUDE.add_argument(
    "--exclude",
    action="append",
    default=None,
    metavar="PATTERN",
    help="Replace exclude patterns; repeatable.",
)
WATCH_UPDATE_EXCLUDE.add_argument(
    "--clear-exclude",
    action="store_true",
    help="Clear all exclude patterns.",
)
add_metadata_arguments(WATCH_UPDATE, include_append_artists=False)
WATCH_RUN = WATCH_SUBPARSERS.add_parser("run", help="Run all rules in the foreground.")
WATCH_RUN.add_argument(
    "--observer",
    choices=("auto", "native", "polling"),
    default="auto",
    help="Filesystem event backend (default: auto).",
)
WATCH_SUBPARSERS.add_parser(
    "start", help="Install or update and start the watch service."
)
WATCH_SUBPARSERS.add_parser("stop", help="Stop the managed watch service.")
WATCH_SUBPARSERS.add_parser("status", help="Show managed watch-service status.")
WATCH_SUBPARSERS.add_parser(
    "uninstall", help="Stop and remove the managed watch service."
)


def _collect_metadata(args: argparse.Namespace) -> dict[Tags, str | list[str] | int]:
    """Extract provided tag options from parsed arguments.

    :param args: Parsed argparse namespace.
    :return: Tags explicitly supplied by the caller.
    """
    return {
        tag: value
        for tag in Tags
        if (value := getattr(args, tag.lower(), None)) is not None
    }


def _updated_rule_from_args(args: argparse.Namespace, existing: WatchRule) -> WatchRule:
    """Create a validated replacement rule from supplied update options.

    Omitted options retain the corresponding stored value. Supplied metadata
    tags replace only those tags; repeatable include/exclude flags replace the
    entire respective list.

    :param args: Parsed ``watch update`` options.
    :param existing: Current stored rule.
    :return: Validated replacement with the existing rule ID.
    """
    metadata = dict(existing.metadata)
    metadata.update(normalize_metadata(_collect_metadata(args)))
    include = (
        []
        if args.clear_include
        else args.include
        if args.include is not None
        else existing.include
    )
    exclude = (
        []
        if args.clear_exclude
        else args.exclude
        if args.exclude is not None
        else existing.exclude
    )
    return WatchRule.create(
        id=existing.id,
        root=args.root if args.root is not None else Path(existing.root),
        include=include,
        exclude=exclude,
        priority=existing.priority if args.priority is None else args.priority,
        metadata=metadata,
    )


def _handle_watch(argv: list[str]) -> int:
    """Dispatch declarative watch CLI commands and convert usage errors to status.

    The watch service runs in the foreground and must make its diagnostics
    visible on stderr for a supervising service manager.

    :param argv: Arguments following ``watch``.
    :return: Process exit status.
    """
    try:
        args = WATCH_PARSER.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    setup_logging(1)
    store = RuleStore(get_watch_store_path())
    try:
        if args.action == "add":
            metadata = normalize_metadata(_collect_metadata(args))
            rule = WatchRule.create(
                root=args.root,
                include=args.include or ["*"],
                exclude=args.exclude,
                priority=args.priority,
                metadata=metadata,
            )
            store.add(rule)
            print(rule.id)
            return 0
        if args.action == "list":
            for rule in store.load():
                print(
                    f"{rule.id}\t{rule.root}\tpriority={rule.priority}\t"
                    f"{','.join(rule.include)}\t{rule.metadata}"
                )
            return 0
        if args.action == "update":
            if store.update(
                args.id, lambda existing: _updated_rule_from_args(args, existing)
            ):
                return 0
            print(f"Watch rule not found: {args.id}", file=sys.stderr)
            return 1
        if args.action == "remove":
            if store.remove(args.id):
                return 0
            print(f"Watch rule not found: {args.id}", file=sys.stderr)
            return 1
        if args.action in {"start", "stop", "status", "uninstall"}:
            manager = WatchServiceManager(store)
            operation = getattr(manager, args.action)
            status = operation()
            state = "running" if status.running else "stopped"
            if args.action == "start":
                print(f"started {status.backend} service {status.name}")
            elif args.action == "uninstall":
                print(f"uninstalled {status.backend} service {status.name}")
            else:
                installed = "installed" if status.installed else "not installed"
                print(f"{status.backend} service {status.name}: {installed}, {state}")
            return 0
        if args.action == "run":
            logger = setup_watch_logging(get_watch_log_path(store.path))
            return WatchService(store, observer_mode=args.observer, logger=logger).run()
        raise RuntimeError(f"Unhandled watch action: {args.action}")
    except (OSError, ServiceManagerError, TypeError, ValueError) as exc:
        print(f"autometa watch: error: {exc}", file=sys.stderr)
        return 2


def _run_metadata(args: argparse.Namespace) -> int:
    """Apply non-watch metadata arguments using the established manual behavior.

    :param args: Parsed normal metadata CLI arguments.
    :return: Process exit status.
    """
    logger = setup_logging(args.verbose)
    config = Config.load(args.rulefile) if args.rulefile else None
    cli_metadata = _collect_metadata(args)
    for filename in glob.glob(args.filespec):
        path = Path(filename)
        try:
            media = MusicFile(path)
        except UnsupportedFileTypeError as exc:
            warnings.warn(f"Skipping unsupported file {path.name}: {exc}")
            continue
        metadata = config.get_tags_for_file(path) if config else {}
        metadata.update(cli_metadata)
        for tag, value in metadata.items():
            if tag == Tags.ARTIST:
                artists = value.split(",") if isinstance(value, str) else value
                if args.append_artists and (existing := media[Tags.ARTIST]):
                    artists = (
                        existing if isinstance(existing, list) else [existing]
                    ) + artists
                media[tag] = artists
            else:
                media[tag] = str(value)
        media.save()
        logger.debug("Saved metadata for %s", path)
    return 0


def main(args: list[str] | None = None) -> int:
    """Run the CLI and return an explicit process status.

    :param args: Optional argument sequence, excluding executable name.
    :return: Process exit status.
    """
    argv = list(sys.argv[1:] if args is None else args)
    if argv and argv[0] == "watch":
        return _handle_watch(argv[1:])
    try:
        parsed = PARSER.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    return _run_metadata(parsed)


def console_main() -> None:
    """Invoke :func:`main` with console-script exit semantics.

    :return: None.
    """
    raise SystemExit(main())
