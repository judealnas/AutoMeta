import os
import tempfile
import unittest
import logging
import pathlib

from autometa.util.tempcpy import TemporaryCopy


class TemporaryCopyTestCase(unittest.TestCase):
    logger = logging.getLogger("TemporaryCopyTestCase")

    def test_temp_txt(self):
        """Test creating a temporary copy of TXT files."""
        contents = "Hello, world!"
        # Create a temporary directory in which to create a temporary source file
        with tempfile.TemporaryDirectory() as srcdir:

            # Create a temp file in the temp dir
            # After writing, close file to allow copying.
            # delete=False so that closing file does not delete it.
            # File will be automatically deleted with the ``srcdir``.
            with tempfile.NamedTemporaryFile(
                suffix=".txt", mode="w+", delete=False, dir=srcdir
            ) as temp_file:
                self.logger.debug("Temporary file: %s", temp_file.name)
                temp_file.write(contents)

            assert os.path.exists(temp_file.name), "Temporary src file does not exist."

            # Create a temporary copy of the file
            with TemporaryCopy(temp_file.name) as temp_copy:
                self.logger.debug("Temporary copy: %s", temp_copy)
                assert temp_copy.exists()
                with open(temp_copy, "r") as temp_copy_file:
                    content = temp_copy_file.read()
                    self.assertEqual(content, contents)

    def _test_copy(self, filepath):
        """Test creating a temporary copy of a file. Check that tag data is also copied."""
        import mutagen
        from mutagen.id3 import TIT2

        filepath = pathlib.Path(filepath)
        assert filepath.exists(), "Test file does not exist."

        # Set source file tags to known value
        src = mutagen.File(filepath)

        # Create a temporary copy
        with TemporaryCopy(filepath) as temp_copy:
            self.logger.debug("Temporary copy: %s", temp_copy)
            assert temp_copy.exists()

            # Check that tags are copied
            cpy = mutagen.File(temp_copy)
            self.assertDictEqual(dict(src), dict(cpy))

    def test_mp3_copy(self):
        """Test creating a temporary copy of MP3 files. Check that tag data is also copied."""
        filepath = pathlib.Path("tests", "silent.mp3")
        self._test_copy(filepath)

    def test_wav_copy(self):
        """Test creating a temporary copy of WAV files. Check that tag data is also copied."""
        filepath = pathlib.Path("tests", "silent.wav")
        self._test_copy(filepath)

    def test_flac_copy(self):
        """Test creating a temporary copy of FLAC files. Check that tag data is also copied."""
        filepath = pathlib.Path("tests", "silent.flac")
        self._test_copy(filepath)


if __name__ == "__main__":
    unittest.main()
