"""Map base tags to ID3v2.3 tags."""

from autometa.tags import Tags

id3_tag_map = {
    Tags.TITLE: "TIT2",
    Tags.ALBUM: "TALB",
    Tags.ARTIST: "TPE1",
    Tags.AUTHOR: "TPE2",
    Tags.GENRE: "TCON",
    Tags.COMMENT: "COMM",
    Tags.YEAR: "TYER",
    Tags.TRACK: "TRCK",
}
"""Map generic tags to supported ID3v2.3 tags."""
