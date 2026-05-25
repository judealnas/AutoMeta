from dataclasses import dataclass
from typing import Mapping
from pathlib import Path
import logging

import yaml

from autometa.types import PathLike
from autometa.tags import Tags

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchConfig:
    enable: bool


def _parse_watch(doc: Mapping, *, doc_desc: str) -> WatchConfig | None:
    if "watch" not in doc:
        LOGGER.debug("%s: no 'watch' key present", doc_desc)
        return None

    watch = doc.get("watch")
    if watch is None:
        LOGGER.debug("%s: 'watch' is explicitly null", doc_desc)
        return None

    if not isinstance(watch, Mapping):
        LOGGER.error(
            "%s: 'watch' must be a mapping, got %s", doc_desc, type(watch).__name__
        )
        raise TypeError(f"{doc_desc}: 'watch' must be a mapping")

    if "enable" not in watch:
        LOGGER.error("%s: 'watch.enable' missing in watch mapping", doc_desc)
        raise ValueError(
            f"{doc_desc}: 'watch.enable' is required when 'watch' is provided"
        )

    enable = watch["enable"]
    if not isinstance(enable, bool):
        LOGGER.error(
            "%s: 'watch.enable' must be a boolean, got %s",
            doc_desc,
            type(enable).__name__,
        )
        raise TypeError(f"{doc_desc}: 'watch.enable' must be a boolean")

    LOGGER.debug("%s: parsed watch.enable=%s", doc_desc, enable)
    return WatchConfig(enable=enable)


class ConfigRule:
    """Represents a configuration rule with pattern and tags."""

    def __init__(
        self,
        pattern: str,
        tags: dict[Tags, str | list[str]],
        priority: int = 0,
        watch: WatchConfig | None = None,
        base_path: Path | None = None,
    ):
        self.pattern = pattern
        self.tags = tags
        self.priority = priority  # Higher priority = more specific
        self.watch = watch
        self.base_path = base_path
        LOGGER.debug(
            "Created ConfigRule(pattern=%s, priority=%s, watch=%s)",
            pattern,
            priority,
            bool(watch),
        )

    def matches(self, filepath: PathLike) -> bool:
        """Check if this rule matches the given file path."""
        return Path(filepath).match(self.pattern)

    def calculate_priority(self) -> int:
        """Calculate priority based on pattern specificity.

        More specific patterns get higher priority:
        - Exact filename (no wildcards) = highest
        - Patterns with directory depth = higher
        - Patterns with wildcards = lower
        """
        if "*" not in self.pattern and "?" not in self.pattern:
            return 1000  # Exact match

        # Count directory separators (deeper = more specific)
        depth = self.pattern.count("/") + self.pattern.count("\\")

        # Count wildcards (fewer = more specific)
        wildcards = self.pattern.count("*") + self.pattern.count("?")

        # Depth adds points, wildcards subtract
        # Base priority of 500 to keep values positive
        return 500 + (depth * 100) - (wildcards * 10)


class Config:
    """Configuration manager for autometa."""

    def __init__(self):
        self.defaults: dict[Tags, str | list[str]] = {}
        self.rules: list[ConfigRule] = []
        self.watch: WatchConfig | None = None

    def get_tags_for_file(self, filepath: PathLike) -> dict[Tags, str | list[str]]:
        """Get the effective tags for a specific file.

        Args:
            filepath: Path to the file

        Returns:
            Dictionary of tags to apply, with defaults overridden by matching rules
        """
        LOGGER.debug("Getting tags for file: %s", filepath)
        # Start with defaults
        tags = self.defaults.copy()

        # Find all matching rules and sort by priority
        matching_rules = [rule for rule in self.rules if rule.matches(filepath)]
        matching_rules.sort(key=lambda r: r.priority)

        LOGGER.debug("Found %d matching rules for %s", len(matching_rules), filepath)

        # Apply rules in order (lower priority first, so higher priority overwrites)
        for rule in matching_rules:
            LOGGER.debug(
                "Applying rule %s (priority=%s) to %s",
                rule.pattern,
                rule.priority,
                filepath,
            )
            tags.update(rule.tags)

        LOGGER.debug("Final tags for %s: %s", filepath, tags)

        return tags

    @classmethod
    def load(cls, file: PathLike) -> "Config":
        """Load configuration from a YAML file.

        The expected format is a list of documents. The first document (optional)
        can contain 'defaults' for global settings. Subsequent documents contain
        a filespec pattern and associated tag criteria.

        Example YAML content:
        ```yaml
        watch:
          enable: true
        defaults:
          artist: ["Default Artist"]
          year: 2024
        ---
        watch:
          enable: true
        filespec: "*.mp3"
        artist: ["Artist X"]
        album: "Standard Album"
        ---
        watch:
          enable: false
        filespec: "album1/feat_*.mp3"
        artist: ["Artist X", "Artist Y"]
        ```

        Args:
            file: The path to the configuration file.

        Returns:
            Config object containing defaults and rules
        """
        LOGGER.info("Loading config from %s", file)
        config = cls()

        with open(file, "r", encoding="utf-8") as f:
            docs = list(yaml.safe_load_all(f))

            LOGGER.debug("Loaded %d documents from %s", len(docs), file)

            for i, doc in enumerate(docs, start=1):
                if doc is None:
                    continue
                if not isinstance(doc, Mapping):
                    LOGGER.error(
                        "config document #%d: expected a mapping, got %s",
                        i,
                        type(doc).__name__,
                    )
                    raise TypeError(
                        f"config document #{i}: expected a mapping, got {type(doc).__name__}"
                    )

                doc_desc = f"config document #{i}"
                doc = dict(doc)

                watch_cfg = _parse_watch(doc, doc_desc=doc_desc)
                doc.pop("watch", None)

                LOGGER.debug("%s: parsed watch config: %s", doc_desc, watch_cfg)

                # Check if this is a defaults document
                if "defaults" in doc:
                    if watch_cfg is not None:
                        config.watch = watch_cfg

                    defaults = doc["defaults"]
                    if not isinstance(defaults, Mapping):
                        LOGGER.error("%s: 'defaults' must be a mapping", doc_desc)
                        raise TypeError(f"{doc_desc}: 'defaults' must be a mapping")

                    for key, value in defaults.items():
                        try:
                            config.defaults[Tags[key.upper()]] = value
                        except KeyError:
                            LOGGER.debug(
                                "%s: skipping unknown default tag: %s", doc_desc, key
                            )
                            # Skip unknown tags
                            continue
                    LOGGER.debug("%s: applied defaults: %s", doc_desc, config.defaults)
                    continue

                # Regular rule document
                if "filespec" not in doc:
                    continue

                filespec = doc.pop("filespec")
                tag_criteria: dict[Tags, str | list[str]] = {}

                for key, value in doc.items():
                    try:
                        tag_criteria[Tags[key.upper()]] = value
                    except (ValueError, KeyError):
                        LOGGER.debug("%s: skipping unknown rule tag: %s", doc_desc, key)
                        # Skip unknown tags
                        continue

                config_dir = Path(file).expanduser().resolve().parent
                rule = ConfigRule(
                    filespec,
                    tag_criteria,
                    watch=watch_cfg,
                    base_path=config_dir,
                )
                rule.priority = rule.calculate_priority()
                config.rules.append(rule)
                LOGGER.debug(
                    "%s: added rule %s with priority %s and tags %s",
                    doc_desc,
                    filespec,
                    rule.priority,
                    tag_criteria,
                )

        LOGGER.info(
            "Loaded config: %d rules, defaults=%s, watch=%s",
            len(config.rules),
            config.defaults,
            config.watch,
        )
        return config
