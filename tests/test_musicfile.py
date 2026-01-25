import pathlib
import tempfile
import unittest

from autometa.core import MusicFile
from autometa.tags import Tags
from autometa.util.tempcpy import TemporaryCopy


class MusicFileMP3TestCase(unittest.TestCase):
    """Test MusicFile with MP3 files."""

    @classmethod
    def setUpClass(cls):
        """Set up test files."""
        cls.test_dir = pathlib.Path(__file__).parent
        cls.mp3_file = cls.test_dir / "silent.mp3"

        # Verify test file exists
        if not cls.mp3_file.exists():
            raise FileNotFoundError(f"Test file not found: {cls.mp3_file}")

    def test_set_title_mp3(self):
        """Test setting title tag on MP3 file."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Test Title"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.TITLE], "Test Title")

    def test_set_artist_mp3(self):
        """Test setting artist tag on MP3 file."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ARTIST] = "Test Artist"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.ARTIST], "Test Artist")

    def test_set_album_mp3(self):
        """Test setting album tag on MP3 file."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ALBUM] = "Test Album"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.ALBUM], "Test Album")

    def test_set_multiple_tags_mp3(self):
        """Test setting multiple tags on MP3 file."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Multi Test Title"
            music[Tags.ARTIST] = "Multi Test Artist"
            music[Tags.ALBUM] = "Multi Test Album"
            music[Tags.GENRE] = "Test Genre"
            music[Tags.YEAR] = "2026"
            music.save()

            # Verify all tags were set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.TITLE], "Multi Test Title")
            self.assertEqual(music_read[Tags.ARTIST], "Multi Test Artist")
            self.assertEqual(music_read[Tags.ALBUM], "Multi Test Album")
            self.assertEqual(music_read[Tags.GENRE], "Test Genre")
            self.assertEqual(music_read[Tags.YEAR], "2026")

    def test_set_multiple_artists_mp3(self):
        """Test setting multiple artists on MP3 file (should be joined)."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ARTIST] = ["Artist One", "Artist Two", "Artist Three"]
            music.save()

            # Verify the artists were joined with semicolon
            music_read = MusicFile(temp_copy)
            self.assertEqual(
                music_read[Tags.ARTIST], "Artist One; Artist Two; Artist Three"
            )

    def test_modify_existing_tag_mp3(self):
        """Test modifying an existing tag on MP3 file."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            # Set initial value
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Original Title"
            music.save()

            # Modify the value
            music_modify = MusicFile(temp_copy)
            music_modify[Tags.TITLE] = "Modified Title"
            music_modify.save()

            # Verify the modification
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.TITLE], "Modified Title")

    def test_get_nonexistent_tag_mp3(self):
        """Test getting a tag that doesn't exist returns None."""
        with TemporaryCopy(self.mp3_file) as temp_copy:
            music = MusicFile(temp_copy)
            self.assertIsNone(music[Tags.COMMENT])

    def test_add_picture_mp3(self):
        """Test adding a picture to MP3 file."""
        # Create a simple 1x1 pixel test image
        with tempfile.NamedTemporaryFile(
            suffix=".jpg", delete=False
        ) as temp_img:
            # Minimal JPEG header + data
            temp_img.write(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
                b"\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06"
                b"\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b"
                b"\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
                b"\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff"
                b"\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff"
                b"\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05"
                b"\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01"
                b"\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01"
                b"\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x14"
                b"\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n"
                b"\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZ"
                b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92"
                b"\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6"
                b"\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba"
                b"\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5"
                b"\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8"
                b"\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff"
                b"\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xfe(\xff\xd9"
            )
            temp_img_path = temp_img.name

        try:
            with TemporaryCopy(self.mp3_file) as temp_copy:
                music = MusicFile(temp_copy)
                music.add_picture(temp_img_path, picture_type=3)
                music.save()

                # Verify picture was added by checking with mutagen
                from mutagen.mp3 import MP3

                audio = MP3(temp_copy)
                # Check for APIC frames (may have description appended)
                apic_found = any(
                    key.startswith("APIC") for key in audio.tags.keys()
                )
                self.assertTrue(apic_found, "APIC frame not found")
                # Find the APIC frame and check its properties
                for key in audio.tags.keys():
                    if key.startswith("APIC"):
                        self.assertEqual(audio.tags[key].type, 3)
                        self.assertEqual(audio.tags[key].mime, "image/jpeg")
                        break
        finally:
            # Clean up test image
            pathlib.Path(temp_img_path).unlink()


class MusicFileFLACTestCase(unittest.TestCase):
    """Test MusicFile with FLAC files."""

    @classmethod
    def setUpClass(cls):
        """Set up test files."""
        cls.test_dir = pathlib.Path(__file__).parent
        cls.flac_file = cls.test_dir / "silent.flac"

        # Verify test file exists
        if not cls.flac_file.exists():
            raise FileNotFoundError(f"Test file not found: {cls.flac_file}")

    def test_set_title_flac(self):
        """Test setting title tag on FLAC file."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Test Title FLAC"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.TITLE], "Test Title FLAC")

    def test_set_artist_flac(self):
        """Test setting artist tag on FLAC file."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ARTIST] = "Test Artist FLAC"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.ARTIST], "Test Artist FLAC")

    def test_set_album_flac(self):
        """Test setting album tag on FLAC file."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ALBUM] = "Test Album FLAC"
            music.save()

            # Verify the tag was set
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.ALBUM], "Test Album FLAC")

    def test_set_multiple_tags_flac(self):
        """Test setting multiple tags on FLAC file."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Multi Test Title FLAC"
            music[Tags.ARTIST] = "Multi Test Artist FLAC"
            music[Tags.ALBUM] = "Multi Test Album FLAC"
            music[Tags.GENRE] = "Test Genre FLAC"
            music[Tags.YEAR] = "2026"
            music.save()

            # Verify all tags were set
            music_read = MusicFile(temp_copy)
            self.assertEqual(
                music_read[Tags.TITLE], "Multi Test Title FLAC"
            )
            self.assertEqual(
                music_read[Tags.ARTIST], "Multi Test Artist FLAC"
            )
            self.assertEqual(
                music_read[Tags.ALBUM], "Multi Test Album FLAC"
            )
            self.assertEqual(music_read[Tags.GENRE], "Test Genre FLAC")
            self.assertEqual(music_read[Tags.YEAR], "2026")

    def test_set_multiple_artists_flac(self):
        """Test setting multiple artists on FLAC file (stored as list)."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ARTIST] = ["Artist One", "Artist Two", "Artist Three"]
            music.save()

            # Verify the artists are stored as a list
            music_read = MusicFile(temp_copy)
            artists = music_read[Tags.ARTIST]
            self.assertIsInstance(artists, list)
            self.assertEqual(len(artists), 3)
            self.assertIn("Artist One", artists)
            self.assertIn("Artist Two", artists)
            self.assertIn("Artist Three", artists)

    def test_set_single_artist_returns_string_flac(self):
        """Test setting single artist returns a string, not a list."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            music[Tags.ARTIST] = "Single Artist"
            music.save()

            # Verify single value returns as string
            music_read = MusicFile(temp_copy)
            artist = music_read[Tags.ARTIST]
            self.assertIsInstance(artist, str)
            self.assertEqual(artist, "Single Artist")

    def test_modify_existing_tag_flac(self):
        """Test modifying an existing tag on FLAC file."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            # Set initial value
            music = MusicFile(temp_copy)
            music[Tags.TITLE] = "Original Title FLAC"
            music.save()

            # Modify the value
            music_modify = MusicFile(temp_copy)
            music_modify[Tags.TITLE] = "Modified Title FLAC"
            music_modify.save()

            # Verify the modification
            music_read = MusicFile(temp_copy)
            self.assertEqual(music_read[Tags.TITLE], "Modified Title FLAC")

    def test_get_nonexistent_tag_flac(self):
        """Test getting a tag that doesn't exist returns None."""
        with TemporaryCopy(self.flac_file) as temp_copy:
            music = MusicFile(temp_copy)
            self.assertIsNone(music[Tags.COMMENT])

    def test_add_picture_flac(self):
        """Test adding a picture to FLAC file."""
        # Create a simple 1x1 pixel test image
        with tempfile.NamedTemporaryFile(
            suffix=".jpg", delete=False
        ) as temp_img:
            # Minimal JPEG header + data
            temp_img.write(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
                b"\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06"
                b"\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b"
                b"\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
                b"\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff"
                b"\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff"
                b"\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05"
                b"\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01"
                b"\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01"
                b"\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x14"
                b"\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n"
                b"\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZ"
                b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92"
                b"\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6"
                b"\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba"
                b"\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5"
                b"\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8"
                b"\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff"
                b"\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xfe(\xff\xd9"
            )
            temp_img_path = temp_img.name

        try:
            with TemporaryCopy(self.flac_file) as temp_copy:
                music = MusicFile(temp_copy)
                music.add_picture(temp_img_path, picture_type=3)
                music.save()

                # Verify picture was added by checking with mutagen
                from mutagen.flac import FLAC

                audio = FLAC(temp_copy)
                self.assertGreater(len(audio.pictures), 0)
                self.assertEqual(audio.pictures[0].type, 3)
                self.assertEqual(audio.pictures[0].mime, "image/jpeg")
        finally:
            # Clean up test image
            pathlib.Path(temp_img_path).unlink()


if __name__ == "__main__":
    unittest.main()
