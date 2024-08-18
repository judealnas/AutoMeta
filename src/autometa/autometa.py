import argparse
import pathlib


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
        "--artist",
        type=str,
        help="Comma-separated sequence of artist names.",
    )

    parser.add_argument(
        "--append-artists",
        action="store_true",
        help="Combine new artist names with existing instead of replacing.",
    )

    parser.add_argument(
        "--album",
        type=str,
        help="Album name.",
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Title of the track.",
    )
    parser.add_argument(
        "--track",
        type=int,
        help="Track number.",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Year of release.",
    )
    parser.add_argument(
        "--genre",
        type=str,
        help="Genre of the track.",
    )
    parser.add_argument(
        "--comment",
        type=str,
        help="Comment.",
    )

    args = parser.parse_args()

    # Process file extensions
    file_extensions = {ext.strip().lower() for ext in args.extensions.split(",")}
    log_file_path = os.path.join(args.path, ".autometa", "logs")

    start_monitoring(args.path, file_extensions, log_file_path)
