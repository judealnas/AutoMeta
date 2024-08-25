import pathlib
import typing
import abc

from autometa.tags import Tags

FILE_T = typing.Union[str, pathlib.Path]


class Mutator(abc.ABC):

    def __init__(self, file: FILE_T):
        self.__file = pathlib.Path(file)

    @property
    def file(self) -> pathlib.Path:
        """File whose tags are to be mutated."""
        return self.__file

    @abc.abstractmethod
    def tags(self) -> typing.Mapping[Tags, typing.Any]:
        """Mapping of tags to values."""

    @abc.abstractmethod
    def save(self, file: typing.Optional[FILE_T] = None):
        """Save the tags to the file."""
