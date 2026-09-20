import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autometa.cli import main
from autometa.watch_store import (
    ENV_STORE_PATH,
    WatchSpec,
    acquire_liveness_lock,
    is_watch_running,
    load_watch_store,
    save_watch_store,
)


class WatchCliTestCase(unittest.TestCase):
    def test_watch_save_only_creates_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                main(["watch", "*.mp3", "--year", "2024", "-s"])
                watchers = load_watch_store(store_path)

            self.assertEqual(len(watchers), 1)
            watch = watchers[0]
            self.assertEqual(watch.pattern, "*.mp3")
            self.assertEqual(watch.metadata["year"], "2024")
            self.assertEqual(Path(watch.watch_root).resolve(), Path.cwd().resolve())

    def test_watch_save_only_store_has_config_only(self):
        """The store must never contain runtime status or pid fields."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                main(["watch", "*.mp3", "--year", "2024", "-s"])
                watchers = load_watch_store(store_path)
                data = watchers[0].to_dict()

            self.assertNotIn("status", data)
            self.assertNotIn("pid", data)

    def test_watch_list_outputs_table(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            watch = WatchSpec(
                id=1,
                pattern="*.mp3",
                metadata={"year": "2024"},
                watch_root=str(Path.cwd()),
            )
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                save_watch_store([watch], store_path)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    main(["watch", "list"])
            output = buffer.getvalue()
            self.assertIn("| ID", output)
            self.assertIn("*.mp3", output)
            self.assertIn("year=2024", output)

    def test_watch_list_reports_stopped_when_not_running(self):
        """A watcher with no held lock must list as stopped."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            watch = WatchSpec(
                id=1,
                pattern="*.mp3",
                metadata={"year": "2024"},
                watch_root=str(Path.cwd()),
            )
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                save_watch_store([watch], store_path)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    main(["watch", "list"])
            self.assertIn("stopped", buffer.getvalue())

    def test_watch_start_confirms_lock(self):
        """Start spawns and waits for the runner to hold its lock."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            watch = WatchSpec(
                id=1,
                pattern="*.mp3",
                metadata={"year": "2024"},
                watch_root=str(Path.cwd()),
            )
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                save_watch_store([watch], store_path)
                # Simulate the runner acquiring its lock, as a real start would
                with acquire_liveness_lock(store_path, 1) as lock:
                    lock.seek(0)
                    lock.truncate()
                    lock.write(b"4321")
                    lock.flush()
                    with patch("autometa.cli._spawn_watch_process", return_value=4321):
                        main(["watch", "start", "1"])
                    running, pid = is_watch_running(store_path, 1)
                self.assertTrue(running)
                self.assertEqual(pid, 4321)
                self.assertFalse(is_watch_running(store_path, 1)[0])
