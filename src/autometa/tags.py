"""Supported tags. Actual enum values do not comply with any specific standard."""

import enum
from types import MappingProxyType

from autometa.types import FileTypes


class Tags(enum.StrEnum):
    # Tags for the meta data
    TITLE = "title"
    ALBUM = "album"
    ARTIST = "artist"
    AUTHOR = "author"
    GENRE = "genre"
    COMMENT = "comment"
    YEAR = "year"
    TRACK = "track"
    PICTURE = "picture"


def get_tag_map(file_type: str) -> dict[Tags, str]:
    """Get the tag map for a given file type.

    Args:
        file_type (str): The file type (e.g., 'mp3', 'flac').
    Returns:
        dict[Tags, str]: The tag map for the given file type.
    """

    match file_type:
        case FileTypes.MP3:
            return MappingProxyType(
                {
                    Tags.TITLE.value: "TIT2",
                    Tags.ALBUM.value: "TALB",
                    Tags.ARTIST.value: "TPE1",
                    Tags.AUTHOR.value: "TPE2",
                    Tags.GENRE.value: "TCON",
                    Tags.COMMENT.value: "COMM",
                    Tags.YEAR.value: "TYER",
                    Tags.TRACK.value: "TRCK",
                    Tags.PICTURE.value: "APIC",
                }
            )
        case FileTypes.FLAC | FileTypes.OGG:
            return MappingProxyType(
                {
                    Tags.TITLE.value: "TITLE",
                    Tags.ALBUM.value: "ALBUM",
                    Tags.ARTIST.value: "ARTIST",
                    Tags.AUTHOR.value: "ALBUMARTIST",
                    Tags.GENRE.value: "GENRE",
                    Tags.COMMENT.value: "COMMENT",
                    Tags.YEAR.value: "DATE",
                    Tags.TRACK.value: "TRACKNUMBER",
                    Tags.PICTURE.value: "PICTURE",
                }
            )
        case _:
            raise NotImplementedError(f"File type '{file_type}' is not supported.")
