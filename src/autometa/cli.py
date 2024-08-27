import argparse
import pathlib

from autometa.tags import Tags

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="autometa",
        description="Modify audio file metadata",
    )
    parser.add_argument("filespec", type=pathlib.Path, help="File to modify.")

    # TODO Specify file format
    # JSON? YAML? All of them?
    parser.add_argument(
        "--metafile",
        type=pathlib.Path,
        help="Specify metadata from file.",
    )

    # Tag options
    parser.add_argument(
        f"--{Tags.ARTIST.lower()}",
        type=str,
        help="Comma-separated sequence of artist names.",
    )

    parser.add_argument(
        "--append-artists",
        action="store_true",
        help="Combine new artist names with existing instead of replacing.",
    )

    parser.add_argument(
        f"--{Tags.ALBUM.lower()}",
        type=str,
        help="Album name.",
    )
    parser.add_argument(
        f"--{Tags.TITLE.lower()}",
        type=str,
        help="Title of the track.",
    )
    parser.add_argument(
        f"--{Tags.TRACK.lower()}",
        type=int,
        help="Track number.",
    )
    parser.add_argument(
        f"--{Tags.YEAR.lower()}",
        type=int,
        help="Year of release.",
    )
    parser.add_argument(
        f"--{Tags.GENRE.lower()}",
        type=str,
        help="Genre of the track.",
    )
    parser.add_argument(
        f"--{Tags.COMMENT.lower()}",
        type=str,
        help="Comment.",
    )

    args = parser.parse_args()
