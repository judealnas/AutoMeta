"""Background process runner for configured file watchers.

This module is executed as a separate process by the watch CLI to run a
configured watcher in the background. It loads the watcher specification
from the watch store, acquires the watcher's liveness lock, and starts
monitoring the target directory.

The runner is the sole owner of its liveness lock: while it runs it holds
``<store_dir>/<id>.lock`` open, and the lock is released automatically when
the process exits (gracefully or otherwise). Run state is derived from this
lock by the CLI -- it is never persisted to the watch store.
"""

import argparse
from pathlib import Path
import os
import signal
import threading

from autometa.watcher import (
    build_metadata_observer_for_watch,
    start_observers,
    stop_observers,
)
from autometa.watch_store import (
    acquire_liveness_lock,
    load_watch_store,
    metadata_to_tags,
)
from autometa.logging_util import setup_logging


def main(args: list[str] | None = None) -> int:
    """Run a configured watcher process.

    Loads a watcher specification by ID from the given store, validates the
    watch root directory, acquires the watcher's liveness lock, and starts
    monitoring for file changes. On SIGTERM/SIGINT the observer is stopped
    gracefully and the lock is released via the context exit.

    :param args: Command-line arguments (defaults to sys.argv)
    :return: Exit code (0 on success, 1 on error)
    """
    parser = argparse.ArgumentParser(
        prog="autometa watch-runner",
        description="Run a configured watch in the background.",
    )
    parser.add_argument("id", type=int, help="Watcher ID to run.")
    parser.add_argument(
        "--store",
        type=Path,
        required=True,
        help="Path to the watch store file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity.",
    )
    parsed = parser.parse_args(args)
    logger = setup_logging(parsed.verbose)

    watchers = load_watch_store(parsed.store)
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

    stop_event = threading.Event()

    def _shutdown(signum, frame):
        del signum, frame
        logger.info("Signal received; stopping watcher %s.", watch.id)
        stop_event.set()

    with acquire_liveness_lock(parsed.store, watch.id) as lock:
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()).encode())
        lock.flush()

        start_observers([observer])
        logger.info("Watcher %s started (pid=%s).", watch.id, os.getpid())

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        # Block until SIGTERM/SIGINT sets the event. Exiting this `with`
        # closes the fd, which releases the liveness lock (both on graceful
        # stop and on process death).
        stop_event.wait()

        stop_observers([observer])
        logger.info("Watcher %s stopped cleanly.", watch.id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
