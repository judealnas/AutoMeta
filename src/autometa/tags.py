"""Supported tags. Actual enum values do not comply with any specific standard."""

import enum


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
