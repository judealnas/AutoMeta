# AutoMeta (WIP)

A command-line tool to aid in manipulating audio file meta-data.

## Installation (WIP)

```bash
pip install autometa
```

## Dependencies

- [Mutagen](https://github.com/quodlibet/mutagen)
- [PyYAML](https://github.com/yaml/pyyaml)

## Usage

### Basic Usage

Apply metadata tags to a single file:

```bash
autometa my_music.mp3 --artist="Alice,Bob" --title="Foo" --year=2024
```

Apply metadata to multiple files using glob patterns:

```bash
autometa **/*.mp3 --artist="Bob,Carol"
```

### Configuration Files (Rulefiles)

AutoMeta supports configuration files (rulefiles) that define metadata rules using gitignore-style patterns. This allows you to set metadata for multiple files based on their location and filename.

Use `--rulefile` to specify a configuration file:

```bash
autometa **/*.mp3 --rulefile=music_config.yaml
```

#### Rulefile Format

Rulefiles use YAML format with multiple documents (separated by `---`). Each document can define:
- **defaults**: Global metadata applied to all files
- **filespec patterns**: Specific rules for files matching a pattern

Example `music_config.yaml`:

```yaml
# Global defaults for all files
defaults:
  artist: ["Default Artist"]
  year: 2024

---
# All MP3 files
filespec: "*.mp3"
artist: ["Artist X"]
album: "Standard Album"

---
# Files in a specific directory (more specific)
filespec: "album1/*.mp3"
artist: ["Artist X"]
album: "Album 1"
year: 2020

---
# Files matching a pattern (most specific)
filespec: "album1/feat_*.mp3"
artist: ["Artist X", "Artist Y"]
album: "Album 1 - Collaborations"

---
# Exact file match (highest priority)
filespec: "album1/special_track.mp3"
artist: ["Artist X", "Artist Y", "Artist Z"]
title: "Special Collaboration"
```

#### Priority Rules

AutoMeta applies metadata in the following order (lowest to highest priority):

1. **Defaults** - Global defaults defined in the rulefile
2. **General patterns** - Less specific filespec patterns (e.g., `*.mp3`)
3. **Specific patterns** - More specific patterns with directories (e.g., `album1/*.mp3`)
4. **Exact matches** - Exact filenames (e.g., `album1/track.mp3`)
5. **Command-line arguments** - Always override everything else

Specificity is determined by:
- Exact filenames (no wildcards) = highest priority
- Directory depth (more slashes = more specific)
- Number of wildcards (fewer = more specific)

#### Command-line Override

Command-line arguments always take precedence over rulefile settings:

```bash
# Artist will be "CLI Artist", but album comes from rulefile
autometa my_music.mp3 --rulefile=music_config.yaml --artist="CLI Artist"
```

### Available Tags

- `--artist`: Comma-separated list of artists
- `--album`: Album name
- `--title`: Track title  
- `--track`: Track number
- `--year`: Release year
- `--genre`: Music genre
- `--append-artists`: Append new artists instead of replacing

**Subject to change**
Supported config file types are YAML, JSON, INI, or TOML.
The type is inferred from the file extension.
If no extension given, AutoMeta tries different decoders until one works

### Automated Watch Service

Watch rules are declarative and are run by one foreground service. Autometa can
install a per-user background supervisor on Linux, macOS, and Windows:

```bash
# Install/update and start the native per-user service.
autometa watch start
autometa watch status

# Stop it without removing the service definition, or remove it entirely.
autometa watch stop
autometa watch uninstall
```

`start` uses a systemd user unit on Linux, a launchd LaunchAgent on macOS, and a
Task Scheduler logon task on Windows. It records the selected backend beside the
rule store, so `stop`, `status`, and `uninstall` continue to target the service
originally installed for that configuration. `autometa watch run` remains
available for debugging and for users who supply their own supervisor.

#### Apply watcher rules from a file

Use a **separate, user-authored YAML file** for complex watcher rules. It is not
the one-off `--rulefile` format above, and it is not the internal `watchers.yaml`
store. For example, with `music-watch.yaml` beside an existing `music/` directory
containing `live/`:

```yaml
version: 1
root: music
rules:
  - name: defaults
    include: ["**/*.mp3", "**/*.flac"]
    exclude: ["**/*.part"]
    metadata:
      artist: ["Alice", "Bob"]
      genre: Classical
  - name: live
    root: music/live
    include: ["*.mp3"]
    priority: 100
    metadata:
      genre: Live
```

```bash
autometa watch apply music-watch.yaml
autometa watch list
```

The file is **one YAML mapping** (not `---`-separated documents):

| Field | Required | Meaning |
| --- | --- | --- |
| `version` | Yes | Integer `1`. This is the *user file* version, not the internal store version. |
| `root` | No | Shared default directory for rules without their own `root`. |
| `rules` | Yes | List of rule mappings. `[]` is valid. |

Each entry in `rules` accepts:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Unique, nonempty string within this file; no leading/trailing whitespace. Keeps the same rule ID across applies. |
| `root` | If no file-level `root` | Existing directory for this rule. **Replaces** the file-level default, rather than being appended to it. |
| `include` | No | List of root-relative `/`-separated glob patterns; defaults to `["*"]`. `[]` disables matches. |
| `exclude` | No | List of root-relative glob patterns to omit; defaults to `[]`. |
| `priority` | No | Integer precedence for overlapping rules; defaults to `0`. Higher wins for the same tag. |
| `metadata` | Yes | Nonempty mapping of tag names to desired values. |

**Root paths are independent:** both the file-level and rule-level `root` are
resolved relative to the *YAML file's directory*, not the current shell directory
and not to each other. In the example, if the YAML file is at
`/home/me/music-watch.yaml`, `defaults` uses `/home/me/music`, and `live` uses
`/home/me/music/live`. Setting the rule's `root: live` would instead use
`/home/me/live`. Absolute paths and `~` also work. Each effective root must
already be a directory when applied.

Patterns match file paths **relative to each rule's effective root**: `*.mp3`
matches there, while `**/*.mp3` also matches in subdirectories. Patterns must
be nonempty, relative, use `/` instead of `\`, and cannot contain `..` path
components. Lists of patterns must be YAML lists, not single strings or `null`.

Supported metadata keys are `title`, `album`, `artist`, `author`, `genre`,
`comment`, `year`, `track`, and `picture`. Values may be nonempty strings,
integers, or nonempty lists of strings; integers are stored as strings. Quote
numeric values if you want them kept explicitly as strings. Unknown or duplicate
fields, unknown tags, malformed values, and missing required fields are rejected
without modifying the store. Matching rules contribute disjoint tags; for a
shared tag, higher priority wins, then the deeper root at equal priority. If
conflicting values tie on both, that audio file is skipped during reconciliation.

After editing, run `watch apply` again. It updates rules with the same names and
removes rules omitted from **that file only**; CLI-added rules and rules from
other files remain. `rules: []` removes this file's rules. Invalid or missing
files leave the store unchanged. A running watcher reloads after a successful
change; `apply` itself does not start it. `watch list` includes `source=<path>`
for file-owned rules. Manual `watch update` or `remove` of a file-owned rule is
temporary: the next apply restores the file's definition. Moving or renaming
the rule file makes it a new source; remove the old source's rules first.

An apply that changes rules upgrades the internal store to version 4 while
preserving older rules. Back up that store before downgrading AutoMeta to an
older version.

### Watch Log Inspection

Each `autometa watch run` writes durable JSONL audit records beside its rule
store. The default store therefore writes to
`~/.config/autometa/.watchers.yaml.log` on Linux/macOS and
`%APPDATA%\\autometa\\.watchers.yaml.log` on Windows. Records include UTC
timestamps, severity, event type, paths, rule IDs, and changed tag names; they
do not contain metadata values. The active file rotates at 5 MiB and keeps five
archives.

```bash
# Show the log location and the 50 newest records.
autometa logs path
autometa logs

# Filter one file's history, failures, or a recent time range.
autometa logs file /music/album/track.mp3
autometa logs failures --since 24h
autometa logs --event watch.metadata_updated --rule <uuid> --json

# Aggregate matching records or follow new records.
autometa logs summary
autometa logs --follow --level ERROR

# Destructive: stop the watcher first, then remove the active and rotated logs.
autometa watch stop
autometa logs clear --yes
```

`--path`, `--rule`, `--event`, `--level`, `--since`, and `--tail` can be
combined. `--json` preserves JSONL output for shell or PowerShell processing.

```bash
# Patterns are relative to the concrete root; ** expresses any directory depth.
autometa watch add /music --include "**/*.mp3" --include "**/*.flac" \
  --exclude "**/*.part" --artist="Alice,Bob" --year=2024

# One rule can cover dynamically created matching project directories.
autometa watch add 'C:/Users/Jude/Music/Jude Tunes' \
  --include '* Project/*.mp3' --include '* Project/*.flac' --year=2026

# A deeper root overrides a broader root at the same priority.
autometa watch add /music --include "**/*.mp3" \
  --genre "Classical"
autometa watch add /music/live --include "*.mp3" \
  --genre "Live"
# Explicit priority overrides root depth when needed.
autometa watch update <uuid> --priority 100

# Inspect, update, or remove stored rules. The internal YAML store is managed by
# the CLI; do not edit it manually. Prefer editing and reapplying file-owned rules.
autometa watch list
autometa watch update <uuid> --year 2025
# Priority is preserved when omitted; use it to make a scoped override win.
autometa watch update <uuid> --priority 100

# Repeated include/exclude flags replace that complete list. Omitted fields remain.
autometa watch update <uuid> --include "*.flac" --include "*.ogg"
autometa watch update <uuid> --clear-exclude

# Clear includes explicitly to disable matching until they are replaced later.
autometa watch update <uuid> --clear-include
autometa watch remove <uuid>

# Start the single foreground reconciliation service. ``auto`` selects polling
# for WSL roots under /mnt/<drive>; use ``native`` or ``polling`` to force it.
autometa watch run --observer auto
```

The internal YAML watch store contains rule IDs, source ownership, roots,
include/exclude patterns, priorities, and desired metadata. When a file matches
multiple rules, disjoint metadata tags are merged. For each shared tag, the
highest priority wins; at equal priority, the rule with the deeper root wins.
Rules assigning different values at equal priority and root depth are reported
as a conflict and that file is skipped; no arbitrary write is performed. Writes
are locked and atomic. The service scans matching files at startup, coalesces filesystem event storms, waits for writes to settle, and
reconciles tags idempotently. A malformed file is logged and retried without
stopping the service; if an observer dies, the service exits nonzero so its
supervisor can restart it.
