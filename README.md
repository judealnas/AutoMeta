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

Watch rules are declarative and are run by one foreground service. Use your
service supervisor (systemd, launchd, Windows Service Manager, Docker, etc.) to
keep `autometa watch run` running and restart it after failures.

```bash
# Add a recursive rule. --include can be supplied more than once.
autometa watch add /music --include "*.mp3" --include "*.flac" \
  --exclude "*.part" --recursive --artist="Alice,Bob" --year=2024

# A broad default and a more-specific override. Higher priority wins per tag.
autometa watch add /music --include "*.mp3" --recursive \
  --priority 0 --genre "Classical"
autometa watch add /music/live --include "*.mp3" \
  --priority 100 --genre "Live"

# Inspect, update, or remove stored rules. The YAML store is managed by the CLI;
# do not edit it manually.
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

# Start the single foreground reconciliation service.
autometa watch run
```

The YAML watch store contains rule IDs, roots, include/exclude patterns,
recursive flags, priorities, and desired metadata only. When a file matches
multiple rules, disjoint metadata tags are merged and the highest priority wins
for each shared tag. Equal-priority rules assigning different values to the same
tag are reported as a conflict and that file is skipped; no arbitrary write is
performed. Writes are locked and atomic. The service scans matching files at
startup, coalesces filesystem event storms, waits for writes to settle, and
reconciles tags idempotently. A malformed file is logged and retried without
stopping the service; if an observer dies, the service exits nonzero so its
supervisor can restart it.
