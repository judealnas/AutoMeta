"""Command-line interface for metadata updates and the watch service."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import sys
import warnings

from autometa.config import Config
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.logging_util import setup_logging
from autometa.log_query import (
    format_watch_log_record,
    parse_since,
    query_watch_logs,
    snapshot_watch_log,
    stream_watch_logs,
    summarize_watch_logs,
)
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
    prog="autometa",
    description="Modify audio file metadata",
    epilog="Additional commands: 'autometa watch --help' and 'autometa logs --help'.",
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

LOGS_PARSER = argparse.ArgumentParser(
    prog="autometa logs", description="Inspect structured watch-service logs."
)
LOGS_PARSER.add_argument(
    "mode",
    choices=("path", "summary", "failures", "file", "clear"),
    nargs="?",
    default=None,
    help="Use 'path' to print the log location or 'summary' for aggregate counts.",
)
LOGS_PARSER.add_argument(
    "target",
    nargs="?",
    help="Required file path for 'autometa logs file <PATH>'.",
)
LOGS_PARSER.add_argument(
    "--tail",
    type=int,
    default=50,
    metavar="N",
    help="Show the newest N matching records (default: 50).",
)
LOGS_PARSER.add_argument(
    "--follow", action="store_true", help="Stream new matching records."
)
LOGS_PARSER.add_argument(
    "--yes", action="store_true", help="Confirm destructive log deletion for 'clear'."
)
LOGS_PARSER.add_argument("--json", action="store_true", help="Print JSON output.")
LOGS_PARSER.add_argument("--event", help="Require an exact event identifier.")
LOGS_PARSER.add_argument("--path", help="Require a case-insensitive path substring.")
LOGS_PARSER.add_argument("--rule", dest="rule_id", help="Require an exact rule UUID.")
LOGS_PARSER.add_argument(
    "--level",
    choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    help="Require an exact log severity.",
)
LOGS_PARSER.add_argument(
    "--since",
    metavar="DURATION",
    help="Only include records newer than a duration such as 30m, 2h, or 7d.",
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


def _handle_logs(argv: list[str]) -> int:
    """Query structured watch-service logs without altering the running watcher.

    :param argv: Arguments following ``logs``.
    :return: Process exit status.
    """
    try:
        args = LOGS_PARSER.parse_args(argv)
        since = parse_since(args.since) if args.since else None
        log_path = get_watch_log_path(get_watch_store_path())
        if args.mode == "path":
            if args.follow or args.target is not None:
                raise ValueError(
                    "autometa logs path does not accept a target or --follow."
                )
            print(log_path)
            return 0
        if args.mode == "clear":
            if args.follow or args.target is not None:
                raise ValueError(
                    "autometa logs clear does not accept a target or --follow."
                )
            if not args.yes:
                raise ValueError("Refusing to delete logs without --yes.")
            for path in [
                candidate
                for candidate in log_path.parent.glob(f"{log_path.name}*")
                if candidate == log_path
                or candidate.name.removeprefix(f"{log_path.name}.").isdigit()
            ]:
                path.unlink(missing_ok=True)
            print(f"cleared {log_path}")
            return 0
        if args.mode == "file":
            if args.target is None:
                raise ValueError("autometa logs file requires a file path.")
            if args.path is not None:
                raise ValueError("Use either 'logs file <PATH>' or --path, not both.")
            args.path = args.target
        elif args.target is not None:
            raise ValueError(
                "A positional file path is only valid with 'autometa logs file'."
            )
        if args.mode in {"summary", "failures"} and args.follow:
            raise ValueError(f"autometa logs {args.mode} does not support --follow.")
        if args.mode == "failures" and args.level is not None:
            raise ValueError("autometa logs failures does not accept --level.")
        level = "ERROR" if args.mode == "failures" else args.level
        need_follow = args.follow
        if need_follow:
            snapshot = snapshot_watch_log(log_path)
            stream = stream_watch_logs(
                log_path,
                event=args.event,
                path=args.path,
                rule_id=args.rule_id,
                level=level,
                since=since,
                snapshot=snapshot,
            )
        tail = None if args.mode == "summary" or need_follow else args.tail
        records = query_watch_logs(
            log_path,
            tail=tail,
            event=args.event,
            path=args.path,
            rule_id=args.rule_id,
            level=level,
            since=since,
            active_limit=snapshot.offset if need_follow else None,
        )
        if args.mode == "summary":
            summary = summarize_watch_logs(records)
            if args.json:
                print(json.dumps(summary, sort_keys=True))
            else:
                print(f"total={summary['total']}")
                for category in ("levels", "events"):
                    for name, count in summary[category].items():
                        print(f"{category[:-1]} {name}={count}")
            return 0
        _print_log_records(records, as_json=args.json)
        if need_follow:
            for record in stream:
                _print_log_records([record], as_json=args.json)
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except (OSError, ValueError) as exc:
        print(f"autometa logs: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


def _print_log_records(records: list[dict[str, object]], *, as_json: bool) -> None:
    """Print structured watch records as JSONL or concise terminal lines.

    :param records: Records selected by the log query.
    :param as_json: Whether to preserve JSON objects on stdout.
    :return: None.
    """
    for record in records:
        if as_json:
            print(json.dumps(record, sort_keys=True))
        else:
            print(format_watch_log_record(record))


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
    if argv and argv[0] == "logs":
        return _handle_logs(argv[1:])
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
