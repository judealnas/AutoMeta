import argparse
import glob
import pathlib
import time
import warnings

from autometa.tags import Tags
from autometa.core import MusicFile, UnsupportedFileTypeError
from autometa.config import Config
from autometa.watcher import (
    build_metadata_observers,
    start_observers,
    stop_observers,
)

PARSER = argparse.ArgumentParser(
    prog="autometa",
    description="Modify audio file metadata",
)
PARSER.add_argument("filespec", type=str, help="Files to modify.")

PARSER.add_argument(
    "--rulefile",
    type=pathlib.Path,
    help="File containing metadata rules.",
)

# Tag options
PARSER.add_argument(
    f"--{Tags.ARTIST.lower()}",
    type=str,
    help="Comma-separated sequence of artist names.",
)

PARSER.add_argument(
    "--append-artists",
    action="store_true",
    help="Combine new artist names with existing instead of replacing.",
)

PARSER.add_argument(
    f"--{Tags.ALBUM.lower()}",
    type=str,
    help="Album name.",
)
PARSER.add_argument(
    f"--{Tags.TITLE.lower()}",
    type=str,
    help="Title of the track.",
)
PARSER.add_argument(
    f"--{Tags.TRACK.lower()}",
    type=int,
    help="Track number.",
)
PARSER.add_argument(
    f"--{Tags.YEAR.lower()}",
    type=int,
    help="Year of release.",
)
PARSER.add_argument(
    f"--{Tags.GENRE.lower()}",
    type=str,
    help="Genre of the track.",
)
# TODO: Re-activate once comment is supported by Easy ID3
# PARSER.add_argument(
#     f"--{Tags.COMMENT.lower()}",
#     type=str,
#     help="Comment.",
# )

PARSER.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase verbosity.",
)

WATCH_PARSER = argparse.ArgumentParser(
    prog="autometa watch",
    description="Watch files and update metadata based on a rulefile.",
)
WATCH_PARSER.add_argument(
    "rulefile",
    type=pathlib.Path,
    help="File containing metadata rules.",
)
WATCH_PARSER.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase verbosity.",
)


def setup_logging(verbosity: int):
    """Set up logging."""
    import logging

    # Set up logging
    verbosity_level_map = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=verbosity_level_map.get(verbosity, logging.DEBUG),
    )
    return logging.getLogger("autometa:cli")


def main(args: list[str] | None = None):
    # Get file
    args = [] if args is None else list(args)
    if args and args[0] == "watch":
        watch_args = WATCH_PARSER.parse_args(args[1:])
        LOGGER = setup_logging(watch_args.verbose)
        LOGGER.info("Loading rulefile: %s", watch_args.rulefile)
        config = Config.load(watch_args.rulefile)

        observers = build_metadata_observers(config)
        if not observers:
            LOGGER.warning("No watch-enabled rules found. Exiting.")
            return

        start_observers(observers)
        LOGGER.info("Watching for changes (Ctrl+C to stop).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            LOGGER.info("Stopping observers...")
        finally:
            stop_observers(observers)
        return

    args = PARSER.parse_args(args)
    LOGGER = setup_logging(args.verbose)
    append_artists: bool = args.append_artists

    # Load config if provided
    config: Config | None = None
    if args.rulefile:
        LOGGER.info("Loading rulefile: %s", args.rulefile)
        config = Config.load(args.rulefile)

    # Extract metadata from command-line arguments
    cli_metadata = {}
    for tag in Tags:
        value = getattr(args, tag.lower(), None)
        LOGGER.debug("Received %s: %s", tag, value)
        if value is not None:
            cli_metadata[tag] = value

    filepath = args.filespec
    files = glob.glob(str(filepath))
    LOGGER.debug("Globbed files: %s", files)

    for f in files:
        path = pathlib.Path(f)
        LOGGER.debug("Processing file: %s", path)

        try:
            file = MusicFile(path)
        except UnsupportedFileTypeError as e:
            filename = path.parts[-1]
            warnings.warn(f"Skipping unsupported file {filename}: {e}")
            LOGGER.warning("Skipping unsupported file %s: %s", filename, e)
            continue

        # Build metadata: config rules < CLI arguments
        metadata = {}
        if config:
            # Apply config rules for this file
            config_tags = config.get_tags_for_file(path)
            metadata.update(config_tags)
            LOGGER.debug("Config tags for %s: %s", path, config_tags)

        # Override with CLI arguments (higher priority)
        metadata.update(cli_metadata)
        LOGGER.debug("Final metadata for %s: %s", path, metadata)

        # Updating tags
        for tag, value in metadata.items():
            if value is not None:
                LOGGER.debug("Updating %s: %s", tag, value)
                if tag == Tags.ARTIST:
                    LOGGER.debug("Appending artists?: %s", append_artists)
                    # Handle both string (from CLI) and list (from config)
                    if isinstance(value, str):
                        artist_data = value.split(",")
                    else:
                        artist_data = value

                    if append_artists:
                        # Get existing artists
                        existing = file[Tags.ARTIST]
                        if existing:
                            # Combine with new artists
                            if isinstance(existing, list):
                                artist_data = existing + artist_data
                            else:
                                artist_data = [existing] + artist_data
                    file[Tags.ARTIST] = artist_data
                else:
                    file[tag] = str(value)

                LOGGER.debug("New %s: %s", tag, file[tag])

        # Save changes
        LOGGER.debug("Saving changes to %s", path)
        file.save()
