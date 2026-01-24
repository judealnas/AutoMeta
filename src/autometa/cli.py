import argparse
import pathlib
import glob
import warnings

import mutagen.flac
import mutagen.mp3

from autometa.tags import Tags
from autometa.easyid3 import easyid3_tag_map
from autometa.flac import flac_tag_map

PARSER = argparse.ArgumentParser(
    prog="autometa",
    description="Modify audio file metadata",
)
PARSER.add_argument("filespec", type=str, help="Files to modify.")

# TODO Specify file format
# JSON? YAML? All of them?
PARSER.add_argument(
    "--metafile",
    type=pathlib.Path,
    help="Specify metadata from file.",
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

    args = PARSER.parse_args(args)
    LOGGER = setup_logging(args.verbose)
    append_artists: bool = args.append_artists

    # Extract metadata
    metadata = {}
    for tag in Tags:
        value = getattr(args, tag.lower(), None)
        LOGGER.debug("Received %s: %s", tag, value)
        if value is not None:
            metadata[tag] = value

    filepath = args.filespec
    files = glob.glob(str(filepath))
    LOGGER.debug("Globbed files: %s", files)

    for f in files:
        path = pathlib.Path(f)
        LOGGER.debug("Processing file: %s", path)
        match path.suffix.lower():
            case ".mp3":
                tag_map = easyid3_tag_map
                file = mutagen.mp3.EasyMP3(path)
            case ".flac":
                tag_map = flac_tag_map
                file = mutagen.flac.FLAC(path)
            case _:
                warnings.warn(f"Skipping unsupported file type: {path.parts[-1]}")
                LOGGER.warning(f"Skipping unsupported file type: {path.parts[-1]}")
                continue

        # Updating tags
        for tag, value in metadata.items():
            if value is not None:
                LOGGER.debug("Updating %s: %s", tag, value)
                if tag == Tags.ARTIST:
                    LOGGER.debug("Appending artists?: %s", append_artists)
                    artist_data = metadata[Tags.ARTIST].split(",")
                    if append_artists and tag_map[Tags.ARTIST] in file:
                        # Combine new artists
                        file[tag_map[Tags.ARTIST]] += artist_data
                    else:
                        file[tag_map[Tags.ARTIST]] = artist_data
                else:
                    file[tag_map[tag]] = [value]

                LOGGER.debug("New %s: %s", tag, file.get(tag_map[tag], None))

        # Save changes
        LOGGER.debug("Saving changes to %s", path)
        file.save()
