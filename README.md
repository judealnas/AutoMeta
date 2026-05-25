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
watch:
  enable: true
defaults:
  artist: ["Default Artist"]
  year: 2024

---
# All MP3 files
watch:
  enable: true
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

### Automated (WIP)

In addition to manual modification, watchdogs can be set up to monitor for changes to files and to ensure that the metadata is present in the targeted files.

```bash
autometa init [--metadata] [--<tag>]
```
