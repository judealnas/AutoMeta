from enum import StrEnum
from pathlib import Path
import typing

PathLike = typing.Union[str, Path]


class FileTypes(StrEnum):
    MP3 = "mp3"
    FLAC = "flac"
    OGG = "ogg"
