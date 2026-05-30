import shutil
import tempfile
import time
import unittest
from pathlib import Path

from autometa.core import MusicFile
from autometa.tags import Tags
from autometa.watcher import (
    build_metadata_observer_for_watch,
    start_observers,
    stop_observers,
)


class WatcherObserverTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).parent
        cls.mp3_file = cls.test_dir / "silent.mp3"

        if not cls.mp3_file.exists():
            raise FileNotFoundError(f"Test file not found: {cls.mp3_file}")

    def _wait_for_tag(
        self,
        file_path: Path,
        tag: Tags,
        expected: str,
        timeout: float = 5.0,
    ) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if MusicFile(file_path)[tag] == expected:
                return True
            time.sleep(0.1)
        return False

    def test_observer_updates_metadata_on_create(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            watch_root = Path(tmp_dir)
            target_path = watch_root / "new_track.mp3"
            desired_metadata = {Tags.TITLE: "Observed Title"}
            observer = build_metadata_observer_for_watch(
                "*.mp3",
                desired_metadata,
                watch_root=watch_root,
            )

            start_observers([observer])
            try:
                time.sleep(0.2)
                shutil.copy2(self.mp3_file, target_path)
                self.assertTrue(
                    self._wait_for_tag(target_path, Tags.TITLE, "Observed Title")
                )
            finally:
                stop_observers([observer])

    def test_observer_updates_metadata_on_modify(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            watch_root = Path(tmp_dir)
            target_path = watch_root / "modified_track.mp3"
            shutil.copy2(self.mp3_file, target_path)

            music = MusicFile(target_path)
            music[Tags.TITLE] = "Wrong Title"
            music.save()

            desired_metadata = {Tags.TITLE: "Updated Title"}
            observer = build_metadata_observer_for_watch(
                "*.mp3",
                desired_metadata,
                watch_root=watch_root,
            )

            start_observers([observer])
            try:
                time.sleep(0.2)
                target_path.touch()
                self.assertTrue(
                    self._wait_for_tag(target_path, Tags.TITLE, "Updated Title")
                )
            finally:
                stop_observers([observer])


if __name__ == "__main__":
    unittest.main()
