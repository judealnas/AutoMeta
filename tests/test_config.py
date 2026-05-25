"""Tests for the config module."""
import tempfile
import unittest
from pathlib import Path

from autometa.config import Config, ConfigRule, load
from autometa.tags import Tags


class ConfigRuleTestCase(unittest.TestCase):
    """Test ConfigRule functionality."""

    def test_exact_match(self):
        """Test exact filename match."""
        rule = ConfigRule("album1/track.mp3", {Tags.ARTIST: ["Test"]})
        self.assertTrue(rule.matches("album1/track.mp3"))
        self.assertFalse(rule.matches("album1/other.mp3"))

    def test_wildcard_match(self):
        """Test wildcard pattern matching."""
        rule = ConfigRule("*.mp3", {Tags.ARTIST: ["Test"]})
        self.assertTrue(rule.matches("track.mp3"))
        self.assertTrue(rule.matches("song.mp3"))
        self.assertFalse(rule.matches("track.flac"))

    def test_directory_wildcard(self):
        """Test directory wildcard patterns."""
        rule = ConfigRule("album1/*.mp3", {Tags.ARTIST: ["Test"]})
        self.assertTrue(rule.matches("album1/track.mp3"))
        self.assertFalse(rule.matches("album2/track.mp3"))
        self.assertFalse(rule.matches("track.mp3"))

    def test_cross_platform_paths(self):
        """Test path normalization across platforms."""
        rule = ConfigRule("album1/*.mp3", {Tags.ARTIST: ["Test"]})
        # Should work with both forward and backslashes
        self.assertTrue(rule.matches("album1/track.mp3"))
        self.assertTrue(rule.matches("album1\\track.mp3"))

    def test_priority_exact_match(self):
        """Test priority calculation for exact matches."""
        rule = ConfigRule("album1/track.mp3", {Tags.ARTIST: ["Test"]})
        priority = rule.calculate_priority()
        self.assertEqual(priority, 1000)

    def test_priority_with_depth(self):
        """Test priority increases with directory depth."""
        shallow = ConfigRule("*.mp3", {Tags.ARTIST: ["Test"]})
        deep = ConfigRule("album1/*.mp3", {Tags.ARTIST: ["Test"]})
        self.assertGreater(deep.calculate_priority(), shallow.calculate_priority())

    def test_priority_with_wildcards(self):
        """Test priority calculation with wildcards."""
        # Pattern with directory depth and wildcards
        # "*/track.mp3" has directory + exact filename = more specific
        deeper = ConfigRule("*/track.mp3", {Tags.ARTIST: ["Test"]})
        # "*.mp3" has no directory depth = less specific
        shallow = ConfigRule("*.mp3", {Tags.ARTIST: ["Test"]})
        self.assertGreater(
            deeper.calculate_priority(), shallow.calculate_priority()
        )


class ConfigTestCase(unittest.TestCase):
    """Test Config functionality."""

    def test_defaults_only(self):
        """Test getting tags when only defaults are set."""
        config = Config()
        config.defaults = {Tags.ARTIST: ["Default Artist"], Tags.YEAR: "2024"}

        tags = config.get_tags_for_file("any_file.mp3")
        self.assertEqual(tags[Tags.ARTIST], ["Default Artist"])
        self.assertEqual(tags[Tags.YEAR], "2024")

    def test_rule_override_defaults(self):
        """Test that rules override defaults."""
        config = Config()
        config.defaults = {Tags.ARTIST: ["Default Artist"]}
        config.rules = [
            ConfigRule("*.mp3", {Tags.ARTIST: ["Specific Artist"]}, priority=10)
        ]

        tags = config.get_tags_for_file("track.mp3")
        self.assertEqual(tags[Tags.ARTIST], ["Specific Artist"])

    def test_priority_ordering(self):
        """Test that higher priority rules override lower priority ones."""
        config = Config()
        rule1 = ConfigRule("*.mp3", {Tags.ARTIST: ["General"]}, priority=10)
        rule2 = ConfigRule(
            "album1/*.mp3", {Tags.ARTIST: ["Specific"]}, priority=100
        )
        config.rules = [rule1, rule2]

        tags = config.get_tags_for_file("album1/track.mp3")
        self.assertEqual(tags[Tags.ARTIST], ["Specific"])

    def test_multiple_matching_rules(self):
        """Test multiple rules matching the same file."""
        config = Config()
        config.defaults = {Tags.YEAR: "2020"}
        rule1 = ConfigRule("*.mp3", {Tags.ARTIST: ["Artist"]}, priority=10)
        rule2 = ConfigRule("*.mp3", {Tags.ALBUM: ["Album"]}, priority=20)
        config.rules = [rule1, rule2]

        tags = config.get_tags_for_file("track.mp3")
        self.assertEqual(tags[Tags.ARTIST], ["Artist"])
        self.assertEqual(tags[Tags.ALBUM], ["Album"])
        self.assertEqual(tags[Tags.YEAR], "2020")


class LoadConfigTestCase(unittest.TestCase):
    """Test loading config from YAML files."""

    def test_load_with_defaults(self):
        """Test loading config with defaults section."""
        yaml_content = """defaults:
  artist: ["Default Artist"]
  year: 2024
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)
            self.assertEqual(config.defaults[Tags.ARTIST], ["Default Artist"])
            self.assertEqual(config.defaults[Tags.YEAR], 2024)
        finally:
            Path(temp_path).unlink()

    def test_load_with_rules(self):
        """Test loading config with pattern rules."""
        yaml_content = """---
filespec: "*.mp3"
artist: ["Artist X"]
album: "Standard Album"
---
filespec: "album1/*.mp3"
artist: ["Artist Y"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)
            self.assertEqual(len(config.rules), 2)

            # Test general rule
            tags = config.get_tags_for_file("track.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist X"])

            # Test specific rule overrides general
            tags = config.get_tags_for_file("album1/track.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist Y"])
        finally:
            Path(temp_path).unlink()

    def test_load_complete_example(self):
        """Test loading a complete config file."""
        yaml_content = """defaults:
  artist: ["Default Artist"]
  year: 2024
---
filespec: "*.mp3"
artist: ["Artist X"]
album: "Standard Album"
---
filespec: "album1/*.mp3"
artist: ["Artist X"]
album: "Album 1"
year: 2020
---
filespec: "album1/feat_*.mp3"
artist: ["Artist X", "Artist Y"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)

            # Test random MP3 gets defaults + general rule
            tags = config.get_tags_for_file("random.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist X"])
            self.assertEqual(tags[Tags.ALBUM], "Standard Album")
            self.assertEqual(tags[Tags.YEAR], 2024)

            # Test album1 track gets specific album
            tags = config.get_tags_for_file("album1/song.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist X"])
            self.assertEqual(tags[Tags.ALBUM], "Album 1")
            self.assertEqual(tags[Tags.YEAR], 2020)

            # Test featured track gets multiple artists
            tags = config.get_tags_for_file("album1/feat_collaboration.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist X", "Artist Y"])
            self.assertEqual(tags[Tags.ALBUM], "Album 1")
            self.assertEqual(tags[Tags.YEAR], 2020)
        finally:
            Path(temp_path).unlink()

    def test_skip_unknown_tags(self):
        """Test that unknown tags are skipped gracefully."""
        yaml_content = """---
filespec: "*.mp3"
artist: ["Artist"]
unknowntag: "This should be ignored"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)
            tags = config.get_tags_for_file("track.mp3")
            self.assertEqual(tags[Tags.ARTIST], ["Artist"])
            self.assertNotIn("unknowntag", tags)
        finally:
            Path(temp_path).unlink()

    def test_load_watch_enable_on_defaults(self):
        """Test loading watch.enable on the defaults document."""
        yaml_content = """watch:
  enable: false
defaults:
  artist: ["Default Artist"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)
            self.assertIsNotNone(config.watch)
            self.assertFalse(config.watch.enable)
        finally:
            Path(temp_path).unlink()

    def test_load_watch_enable_on_rule(self):
        """Test loading watch.enable on a rule document."""
        yaml_content = """---
filespec: "*.mp3"
watch:
  enable: true
artist: ["Artist X"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            config = load(temp_path)
            self.assertEqual(len(config.rules), 1)
            self.assertIsNotNone(config.rules[0].watch)
            self.assertTrue(config.rules[0].watch.enable)
        finally:
            Path(temp_path).unlink()

    def test_load_watch_requires_enable(self):
        """Test that a watch section must include watch.enable."""
        yaml_content = """---
filespec: "*.mp3"
watch: {}
artist: ["Artist X"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            with self.assertRaises(ValueError):
                load(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_load_watch_enable_must_be_boolean(self):
        """Test that watch.enable must be a boolean."""
        yaml_content = """---
filespec: "*.mp3"
watch:
  enable: "yes"
artist: ["Artist X"]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = f.name

        try:
            with self.assertRaises(TypeError):
                load(temp_path)
        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    unittest.main()
