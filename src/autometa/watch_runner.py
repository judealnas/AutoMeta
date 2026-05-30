"""Background process runner for configured file watchers.

This module is executed as a separate process by the watch CLI to run a
configured watcher in the background. It loads the watcher specification
from persistent storage and starts monitoring the target directory.
"""

import argparse
from pathlib import Path
import time

from autometa.watcher import (
    build_metadata_observer_for_watch,
    start_observers,
    stop_observers,
)
from autometa.watch_store import load_watch_store, metadata_to_tags
from autometa.cli import setup_logging


def main(args: list[str] | None = None) -> int:
    """Run a configured watcher process.

    Loads a watcher specification by ID, validates the watch root directory,
    and starts monitoring for file changes. Catches KeyboardInterrupt to
    gracefully shutdown the observer.

    :param args: Command-line arguments (defaults to sys.argv)
    :return: Exit code (0 on success, 1 on error)
    """
    parser = argparse.ArgumentParser(
        prog="autometa watch-runner",
        description="Run a configured watch in the background.",
    )
    parser.add_argument("id", type=int, help="Watcher ID to run.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity.",
    )
    parsed = parser.parse_args(args)
    logger = setup_logging(parsed.verbose)

    watchers = load_watch_store()
    watch = next((item for item in watchers if item.id == parsed.id), None)
    if watch is None:
        logger.error("Watcher %s not found.", parsed.id)
        return 1

    watch_root = Path(watch.watch_root)
    if not watch_root.exists():
        logger.error("Watch root does not exist: %s", watch_root)
        return 1

    metadata = metadata_to_tags(watch.metadata)
    observer = build_metadata_observer_for_watch(
        watch.pattern, metadata, watch_root=watch_root
    )
    start_observers([observer])
    logger.info("Watcher %s started.", watch.id)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher %s.", watch.id)
    finally:
        stop_observers([observer])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
