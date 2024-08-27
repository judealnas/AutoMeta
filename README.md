# AutoMeta (WIP)

A command-line tool to aid in manipulating audio file meta-data.

## Installation (WIP)

```bash
pip install autometa
```

## Dependencies

- [Mutagen](https://github.com/quodlibet/mutagen)
- [pytaglib](https://github.com/supermihi/pytaglib) (maybe?)
- [watchdog](https://github.com/gorakhargosh/watchdog) (maybe?)

## Usage

### Manual (WIP)

```bash
autometa my_music.mp3 --artist="Alice,Bob" --title="Foo" --year=2024
```

It's also possible to specify a glob pattern to change multiple files at once

```bash
autometa **/*.mp3 --artist="Bob,Carol"
```

Instead of passing metadata through command line, use ``--metadata`` to specify a configuration file containing desired metadata.

```bash
autometa my_music.mp3 --metadata="meta.yml"
```

where ``meta.yml`` contains

```yml
# meta.yml
title: Foo
artist: [Bob, Carol]
```

Tags in the command-line take precedence over those in files.
Hence, the artist data will be set to "Bar" in the following example:

```bash
autometa my_music.mp3 --metadata="meta.yml" --artis=Bar
```

**Subject to change**
Supported config file types are YAML, JSON, INI, or TOML.
The type is inferred from the file extension.
If no extension given, AutoMeta tries different decoders until one works

### Automated (WIP)

In addition to manual modification, watchdogs can be set up to monitor for changes to files and to ensure that the metadata is present in the targeted files.

```bash
autometa init [--metadata] [--<tag>]
```
