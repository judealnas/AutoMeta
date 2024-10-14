import typing
import dataclasses
from autometa.tags import Tags

import configparser


@dataclasses.dataclass
class FileMetaData:
    title: str = None
    album: str = None
    artist: typing.Sequence[str] = None
    author: typing.Sequence[str] = None
    genre: str = None
    comment: str = None
    year: int = None
    track: int = None

    def asdict(self):
        """Return the metadata as a dictionary whose keys are `autometa.tag.Tags` enums."""
        return {
            Tags.TITLE: self.title,
            Tags.ALBUM: self.album,
            Tags.ARTIST: self.artist,
            Tags.AUTHOR: self.author,
            Tags.GENRE: self.genre,
            Tags.COMMENT: self.comment,
            Tags.YEAR: self.year,
            Tags.TRACK: self.track,
        }
