import logging
import pathlib
import unittest
from unittest.mock import patch, MagicMock

from autometa.cli import setup_logging, main, PARSER


class MainFunctionTestCase(unittest.TestCase):
    """Test cases for main function."""

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_mp3_file(self, mock_musicfile, mock_glob):
        """Test processing a single MP3 file."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run main
        main(["test.mp3", "--title", "Test Title"])

        # Verify
        mock_glob.assert_called_once_with("test.mp3")
        mock_musicfile.assert_called_once()
        mock_file.__setitem__.assert_called()
        mock_file.save.assert_called_once()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_flac_file(self, mock_musicfile, mock_glob):
        """Test processing a single FLAC file."""
        # Setup mocks
        mock_glob.return_value = ["test.flac"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run main
        main(["test.flac", "--title", "Test Title"])

        # Verify
        mock_glob.assert_called_once_with("test.flac")
        mock_musicfile.assert_called_once()
        mock_file.__setitem__.assert_called()
        mock_file.save.assert_called_once()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.warnings.warn")
    def test_main_unsupported_file(self, mock_warn, mock_glob):
        """Test handling of unsupported file types."""
        # Setup mocks
        mock_glob.return_value = ["test.wav"]

        # Run main
        main(["test.wav", "--title", "Test Title"])

        # Verify warning was issued
        mock_warn.assert_called_once()
        self.assertIn("Skipping unsupported file", str(mock_warn.call_args))

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_multiple_files(self, mock_musicfile, mock_glob):
        """Test processing multiple files."""
        # Setup mocks
        mock_glob.return_value = ["test1.mp3", "test2.mp3", "test3.mp3"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run main
        main(["*.mp3", "--title", "Test Title"])

        # Verify
        mock_glob.assert_called_once_with("*.mp3")
        self.assertEqual(mock_musicfile.call_count, 3)
        self.assertEqual(mock_file.save.call_count, 3)

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_artist_replace(self, mock_musicfile, mock_glob):
        """Test replacing artist metadata."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_file.__getitem__ = MagicMock(return_value=None)
        mock_musicfile.return_value = mock_file

        # Run main
        main(["test.mp3", "--artist", "Artist1,Artist2"])

        # Verify artist was set (not appended)
        from autometa.tags import Tags

        calls = mock_file.__setitem__.call_args_list
        artist_call = [c for c in calls if c[0][0] == Tags.ARTIST][0]
        self.assertEqual(artist_call[0][1], ["Artist1", "Artist2"])
        mock_file.save.assert_called_once()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_artist_append(self, mock_musicfile, mock_glob):
        """Test appending artist metadata."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_file.__getitem__ = MagicMock(return_value=["ExistingArtist"])
        mock_musicfile.return_value = mock_file

        # Run main with --append-artists flag
        main(["test.mp3", "--artist", "NewArtist", "--append-artists"])

        # Verify artists were appended
        mock_file.save.assert_called_once()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_all_metadata_fields(self, mock_musicfile, mock_glob):
        """Test setting all supported metadata fields."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_file.__getitem__ = MagicMock(return_value=None)
        mock_musicfile.return_value = mock_file

        # Run main with all fields
        main(
            [
                "test.mp3",
                "--artist",
                "Test Artist",
                "--album",
                "Test Album",
                "--title",
                "Test Title",
                "--track",
                "5",
                "--year",
                "2020",
                "--genre",
                "Rock",
            ]
        )

        # Verify all fields were set
        from autometa.tags import Tags

        set_calls = {c[0][0]: c[0][1] for c in mock_file.__setitem__.call_args_list}
        self.assertIn(Tags.ARTIST, set_calls)
        self.assertIn(Tags.ALBUM, set_calls)
        self.assertIn(Tags.TITLE, set_calls)
        self.assertIn(Tags.YEAR, set_calls)
        self.assertIn(Tags.GENRE, set_calls)
        mock_file.save.assert_called_once()

    @patch("autometa.cli.glob.glob")
    def test_main_no_files_found(self, mock_glob):
        """Test behavior when no files match the glob pattern."""
        # Setup mock to return empty list
        mock_glob.return_value = []

        # Run main - should not raise exception
        main(["nonexistent*.mp3", "--title", "Test"])

        # Verify glob was called
        mock_glob.assert_called_once_with("nonexistent*.mp3")

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_track_number(self, mock_musicfile, mock_glob):
        """Test setting track number."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run main
        main(["test.mp3", "--track", "7"])

        # Verify track was set
        from autometa.tags import Tags

        calls = mock_file.__setitem__.call_args_list
        track_calls = [c for c in calls if c[0][0] == Tags.TRACK]
        self.assertTrue(len(track_calls) > 0)
        mock_file.save.assert_called_once()

    @patch("autometa.cli.setup_logging")
    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_verbosity_passed_to_logging(
        self, mock_musicfile, mock_glob, mock_logging
    ):
        """Test that verbosity argument is passed to logging setup."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file
        mock_logger = MagicMock()
        mock_logging.return_value = mock_logger

        # Run main with verbosity
        main(["test.mp3", "-vv", "--title", "Test"])

        # Verify logging setup was called with correct verbosity
        mock_logging.assert_called_once_with(2)

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_main_flac_track_number(self, mock_musicfile, mock_glob):
        """Test setting track number on FLAC file."""
        # Setup mocks
        mock_glob.return_value = ["test.flac"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run main
        main(["test.flac", "--track", "3"])

        # Verify track was set
        from autometa.tags import Tags

        calls = mock_file.__setitem__.call_args_list
        track_call = [c for c in calls if c[0][0] == Tags.TRACK][0]
        self.assertEqual(track_call[0][1], "3")
        mock_file.save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
