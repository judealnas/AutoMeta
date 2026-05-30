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
    load_watch_store,
    save_watch_store,
)


class WatchCliTestCase(unittest.TestCase):
    def test_watch_save_only_creates_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                main(["watch", "*.mp3", "--year", "2024", "-s"])
                watchers = load_watch_store()

            self.assertEqual(len(watchers), 1)
            watch = watchers[0]
            self.assertEqual(watch.pattern, "*.mp3")
            self.assertEqual(watch.metadata["year"], "2024")
            self.assertEqual(Path(watch.watch_root).resolve(), Path.cwd().resolve())

    def test_watch_list_outputs_table(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            watch = WatchSpec(
                id=1,
                pattern="*.mp3",
                metadata={"year": "2024"},
                watch_root=str(Path.cwd()),
                status="stopped",
                pid=None,
            )
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                save_watch_store([watch])
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    main(["watch", "list"])
            output = buffer.getvalue()
            self.assertIn("| ID", output)
            self.assertIn("*.mp3", output)
            self.assertIn("year=2024", output)

    def test_watch_start_updates_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "watchers.yaml"
            watch = WatchSpec(
                id=1,
                pattern="*.mp3",
                metadata={"year": "2024"},
                watch_root=str(Path.cwd()),
                status="stopped",
                pid=None,
            )
            with patch.dict(os.environ, {ENV_STORE_PATH: str(store_path)}):
                save_watch_store([watch])
                with patch("autometa.cli._spawn_watch_process", return_value=4321):
                    main(["watch", "start", "1"])

                watchers = load_watch_store()
            self.assertEqual(watchers[0].status, "running")
            self.assertEqual(watchers[0].pid, 4321)
