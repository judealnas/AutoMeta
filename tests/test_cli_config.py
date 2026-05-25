"""Test CLI integration with config files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from autometa.cli import main
from autometa.tags import Tags


class CLIConfigIntegrationTestCase(unittest.TestCase):
    """Test CLI integration with rulefile."""

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_cli_with_rulefile_only(self, mock_musicfile, mock_glob):
        """Test CLI applies rules from rulefile."""
        # Create a test config
        yaml_content = """---
filespec: "*.mp3"
artist: ["Config Artist"]
album: "Config Album"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            config_path = f.name

        try:
            # Setup mocks
            mock_glob.return_value = ["test.mp3"]
            mock_file = MagicMock()
            mock_musicfile.return_value = mock_file

            # Run CLI with rulefile
            main(["test.mp3", "--rulefile", config_path])

            # Verify config tags were applied
            set_calls = {
                c[0][0]: c[0][1]
                for c in mock_file.__setitem__.call_args_list
            }
            self.assertEqual(set_calls[Tags.ARTIST], ["Config Artist"])
            self.assertEqual(set_calls[Tags.ALBUM], "Config Album")
            mock_file.save.assert_called_once()
        finally:
            Path(config_path).unlink()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_cli_argument_overrides_rulefile(
        self, mock_musicfile, mock_glob
    ):
        """Test that CLI arguments override rulefile."""
        # Create a test config
        yaml_content = """---
filespec: "*.mp3"
artist: ["Config Artist"]
album: "Config Album"
title: "Config Title"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            config_path = f.name

        try:
            # Setup mocks
            mock_glob.return_value = ["test.mp3"]
            mock_file = MagicMock()
            mock_musicfile.return_value = mock_file

            # Run CLI with rulefile AND artist override
            main([
                "test.mp3",
                "--rulefile",
                config_path,
                "--artist",
                "CLI Artist",
            ])

            # Verify CLI artist overrides config, but config album remains
            set_calls = {
                c[0][0]: c[0][1]
                for c in mock_file.__setitem__.call_args_list
            }
            self.assertEqual(set_calls[Tags.ARTIST], ["CLI Artist"])
            self.assertEqual(set_calls[Tags.ALBUM], "Config Album")
            self.assertEqual(set_calls[Tags.TITLE], "Config Title")
            mock_file.save.assert_called_once()
        finally:
            Path(config_path).unlink()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_cli_specific_pattern_overrides_general(
        self, mock_musicfile, mock_glob
    ):
        """Test that specific patterns override general ones."""
        # Create a test config with general and specific rules
        yaml_content = """---
filespec: "*.mp3"
artist: ["General Artist"]
album: "General Album"
---
filespec: "album1/*.mp3"
artist: ["Specific Artist"]
album: "Specific Album"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            config_path = f.name

        try:
            # Setup mocks
            mock_glob.return_value = ["album1/track.mp3"]
            mock_file = MagicMock()
            mock_musicfile.return_value = mock_file

            # Run CLI with rulefile
            main(["album1/track.mp3", "--rulefile", config_path])

            # Verify specific rule was applied
            set_calls = {
                c[0][0]: c[0][1]
                for c in mock_file.__setitem__.call_args_list
            }
            self.assertEqual(set_calls[Tags.ARTIST], ["Specific Artist"])
            self.assertEqual(set_calls[Tags.ALBUM], "Specific Album")
            mock_file.save.assert_called_once()
        finally:
            Path(config_path).unlink()

    @patch("autometa.cli.glob.glob")
    @patch("autometa.cli.MusicFile")
    def test_cli_no_rulefile_uses_args_only(
        self, mock_musicfile, mock_glob
    ):
        """Test that without rulefile, only CLI args are used."""
        # Setup mocks
        mock_glob.return_value = ["test.mp3"]
        mock_file = MagicMock()
        mock_musicfile.return_value = mock_file

        # Run CLI without rulefile
        main(["test.mp3", "--artist", "CLI Artist", "--album", "CLI Album"])

        # Verify only CLI args were applied
        set_calls = {
            c[0][0]: c[0][1] for c in mock_file.__setitem__.call_args_list
        }
        self.assertEqual(set_calls[Tags.ARTIST], ["CLI Artist"])
        self.assertEqual(set_calls[Tags.ALBUM], "CLI Album")
        mock_file.save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
