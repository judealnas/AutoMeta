"""Integration tests for the watch_runner background process."""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from autometa.watch_store import (
    WatchSpec,
    is_watch_running,
    save_watch_store,
)


class WatchRunnerProcessTestCase(unittest.TestCase):
    def _seed_store(self, store: Path, root: Path):
        save_watch_store(
            [
                WatchSpec(
                    id=1,
                    pattern="*.mp3",
                    metadata={"year": "2024"},
                    watch_root=str(root),
                )
            ],
            store,
        )

    def _spawn_runner(self, store: Path) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "autometa.watch_runner",
                "--store",
                str(store),
                "1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _wait_until_running(self, store: Path, timeout: float = 5.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            running, pid = is_watch_running(store, 1)
            if running:
                return pid
            time.sleep(0.05)
        self.fail("Runner never acquired its liveness lock (pid file check)")

    def test_runner_releases_lock_on_sigterm(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Path(tmp_dir) / "watchers.yaml"
            root = Path(tmp_dir) / "music"
            root.mkdir()
            self._seed_store(store, root)

            proc = self._spawn_runner(store)
            try:
                self._wait_until_running(store)
                self.assertTrue(proc.poll() is None, "runner exited prematurely")

                # Send SIGTERM exactly as the CLI stop handler does
                os.kill(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.fail("runner did not exit after SIGTERM")

                self.assertEqual(proc.returncode, 0)
                running, remaining = is_watch_running(store, 1)
                self.assertFalse(running, f"lock still held by pid {remaining}")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_missing_watcher_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Path(tmp_dir) / "watchers.yaml"
            # No watcher with id=1 seeded -> runner should error out
            proc = self._spawn_runner(store)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.fail("runner hung on missing watcher")
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
