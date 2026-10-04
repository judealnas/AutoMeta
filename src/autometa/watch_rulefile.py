"""Parse and validate user-authored watch rule YAML, distinct from the store."""

from pathlib import Path
import uuid

import yaml

from autometa.tags import Tags
from autometa.watch_store import WatchRule


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def construct_mapping(self, node, deep=False):
        """Build a YAML mapping without losing earlier repeated fields.

        :param node: YAML mapping node.
        :param deep: Whether to construct keys and values recursively.
        :return: Constructed mapping.
        :rtype: dict
        :raises ValueError: If any field is repeated.
        """
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML field: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _check_fields(value: object, allowed: set[str], label: str) -> dict:
    """Reject malformed mappings and unexpected fields in a rule source.

    :param value: YAML value to inspect.
    :param allowed: Supported mapping keys.
    :param label: Context for user-facing errors.
    :return: Validated mapping.
    :rtype: dict
    :raises ValueError: If mapping keys are malformed or unknown.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a mapping with string keys.")
    unexpected = value.keys() - allowed
    if unexpected:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unexpected))}")
    return value


def _root_path(value: object, source: Path) -> Path:
    """Resolve a source-relative watch root or a user-expanded absolute root.

    :param value: Root path from YAML.
    :param source: Canonical source file path.
    :return: Absolute path to a root (existence is checked by WatchRule).
    :rtype: Path
    :raises ValueError: If the root is not a nonempty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Watch rule root must be a nonempty path string.")
    root = Path(value).expanduser()
    return root if root.is_absolute() else source.parent / root


def load_watch_rulefile(path: Path) -> tuple[str, list[WatchRule]]:
    """Load a complete user-authored rule set before any store mutation.

    :param path: User-authored YAML path.
    :return: Canonical source identity and validated watch rules.
    :rtype: tuple[str, list[WatchRule]]
    :raises OSError: If the source cannot be read.
    :raises ValueError: If the YAML or a rule is invalid.
    """
    source = path.expanduser().resolve()
    try:
        with source.open(encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid watch rule YAML: {exc}") from exc

    data = _check_fields(data, {"version", "root", "rules"}, "Watch rule file")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported watch rule file version (expected 1).")
    if "root" in data:
        _root_path(data["root"], source)
    entries = data.get("rules")
    if not isinstance(entries, list):
        raise ValueError("Watch rule file 'rules' must be a list.")

    # Validate every rule and name before returning anything to be persisted.
    rules: list[WatchRule] = []
    names: set[str] = set()
    for index, raw in enumerate(entries, start=1):
        entry = _check_fields(
            raw,
            {"name", "root", "include", "exclude", "priority", "metadata"},
            f"Rule #{index}",
        )
        name = entry.get("name")
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError(f"Rule #{index} needs a nonempty, unpadded name.")
        if name in names:
            raise ValueError(f"Duplicate watch rule name: {name}")
        names.add(name)
        root_value = entry.get("root", data.get("root"))
        root = _root_path(root_value, source)
        for field in ("include", "exclude"):
            if field in entry:
                patterns = entry[field]
                if not isinstance(patterns, list) or any(
                    not isinstance(pattern, str) for pattern in patterns
                ):
                    raise ValueError(
                        f"Rule #{index} '{field}' must be a list of strings."
                    )
        metadata = _check_fields(
            entry.get("metadata"),
            {tag.value for tag in Tags},
            f"Rule #{index} metadata",
        )
        for tag, value in metadata.items():
            if type(value) not in (str, int) and not (
                isinstance(value, list)
                and value
                and all(isinstance(item, str) for item in value)
            ):
                raise ValueError(
                    f"Rule #{index} metadata '{tag}' needs a string, integer, or nonempty string list."
                )
        rule = WatchRule.create(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"autometa/watch/{source}/{name}")),
            source=str(source),
            root=root,
            include=entry.get("include"),
            exclude=entry.get("exclude"),
            priority=entry.get("priority", 0),
            metadata=metadata,
        )
        rules.append(rule)
    return str(source), rules
