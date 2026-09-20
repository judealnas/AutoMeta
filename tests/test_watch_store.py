"""Tests for the watch store's liveness-lock helpers."""

import tempfile
import unittest
from pathlib import Path

from autometa.watch_store import (
    WatchSpec,
    acquire_liveness_lock,
    is_watch_running,
    liveness_lock_path,
    save_watch_store,
)


class LivenessLockTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "watchers.yaml"
        self.root = Path(self._tmp.name) / "music"
        self.root.mkdir()

    def _seed(self):
        save_watch_store(
            [
                WatchSpec(
                    id=1,
                    pattern="*.mp3",
                    metadata={"year": "2024"},
                    watch_root=str(self.root),
                )
            ],
            self.store,
        )

    def test_liveness_lock_path_is_colocated(self):
        self.assertEqual(
            liveness_lock_path(self.store, 1), self.store.with_name("1.lock")
        )

    def test_is_running_when_lock_free(self):
        self._seed()
        self.assertEqual(is_watch_running(self.store, 1), (False, None))

    def test_acquire_then_is_running(self):
        self._seed()
        with acquire_liveness_lock(self.store, 1) as lock:
            lock.seek(0)
            lock.truncate()
            lock.write(b"1234")
            lock.flush()
            self.assertEqual(is_watch_running(self.store, 1), (True, 1234))

    def test_second_acquirer_nonblocking_raises(self):
        self._seed()
        with acquire_liveness_lock(self.store, 1):
            with self.assertRaises(BlockingIOError):
                with acquire_liveness_lock(self.store, 1, blocking=False):
                    pass

    def test_lock_released_on_close(self):
        self._seed()
        with acquire_liveness_lock(self.store, 1):
            pass
        # After the with-block exits, the lock must be free
        self.assertEqual(is_watch_running(self.store, 1), (False, None))

    def test_missing_lock_file_returns_not_running(self):
        # No seed -> no lock file exists
        self.assertEqual(is_watch_running(self.store, 99), (False, None))


if __name__ == "__main__":
    unittest.main()
