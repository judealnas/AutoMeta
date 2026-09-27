"""Rulefile configuration for non-watch metadata application."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Mapping

import yaml

from autometa.tags import Tags
from autometa.types import PathLike

LOGGER = logging.getLogger(__name__)


@dataclass
class ConfigRule:
    """A rulefile filename pattern with desired tags.

    :param pattern: Relative filename pattern.
    :param tags: Metadata tags applied by the rule.
    :param priority: Specificity ordering for matching rules.
    :param base_path: Directory containing the source rulefile.
    """

    pattern: str
    tags: dict[Tags, str | list[str]]
    priority: int = 0
    base_path: Path | None = None

    def matches(self, filepath: PathLike) -> bool:
        """Check whether a normalized path matches the rule pattern.

        :param filepath: Candidate path.
        :return: Whether the pattern matches.
        """
        return Path(str(filepath).replace("\\", "/")).match(self.pattern)

    def calculate_priority(self) -> int:
        """Calculate precedence based on path depth and wildcard count.

        :return: Higher values for more-specific rules.
        """
        if "*" not in self.pattern and "?" not in self.pattern:
            return 1000
        return (
            500
            + (self.pattern.count("/") + self.pattern.count("\\")) * 100
            - (self.pattern.count("*") + self.pattern.count("?")) * 10
        )


class Config:
    """Load and apply non-watch rulefile metadata configuration."""

    def __init__(self) -> None:
        """Initialize an empty configuration."""
        self.defaults: dict[Tags, str | list[str]] = {}
        self.rules: list[ConfigRule] = []

    def get_tags_for_file(self, filepath: PathLike) -> dict[Tags, str | list[str]]:
        """Return defaults plus all matching rules in specificity order.

        :param filepath: Candidate file path.
        :return: Effective tag mapping.
        """
        tags = self.defaults.copy()
        for rule in sorted(
            (rule for rule in self.rules if rule.matches(filepath)),
            key=lambda rule: rule.priority,
        ):
            tags.update(rule.tags)
        return tags

    @classmethod
    def load(cls, file: PathLike) -> "Config":
        """Load YAML documents containing defaults and filename rules.

        The obsolete ``watch.enable`` setting is intentionally ignored; watch
        configuration is stored only in the dedicated declarative watch store.

        :param file: YAML rulefile path.
        :return: Loaded configuration.
        :raises TypeError: If YAML documents or defaults are malformed.
        """
        config = cls()
        with open(file, encoding="utf-8") as handle:
            documents = list(yaml.safe_load_all(handle))
        for index, document in enumerate(documents, start=1):
            if document is None:
                continue
            if not isinstance(document, Mapping):
                raise TypeError(
                    f"config document #{index}: expected a mapping, got {type(document).__name__}"
                )
            data = dict(document)
            data.pop("watch", None)
            if "defaults" in data:
                defaults = data["defaults"]
                if not isinstance(defaults, Mapping):
                    raise TypeError(
                        f"config document #{index}: 'defaults' must be a mapping"
                    )
                for key, value in defaults.items():
                    try:
                        config.defaults[Tags[str(key).upper()]] = value
                    except KeyError:
                        continue
                continue
            if "filespec" not in data:
                continue
            pattern = str(data.pop("filespec"))
            tags: dict[Tags, str | list[str]] = {}
            for key, value in data.items():
                try:
                    tags[Tags[str(key).upper()]] = value
                except (KeyError, ValueError):
                    continue
            rule = ConfigRule(
                pattern, tags, base_path=Path(file).expanduser().resolve().parent
            )
            rule.priority = rule.calculate_priority()
            config.rules.append(rule)
        return config
