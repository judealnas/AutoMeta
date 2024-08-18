import typing
import abc
import pathlib
import taglib

PATH = typing.Union[str, pathlib.Path]


class BaseConfig(abc.ABC):
    """Base class for configuration objects.

    :param filepath: Path to configuration file.
    :type filepath: str or pathlib.Path
    """

    @abc.abstractmethod
    def __init__(self, filepath: PATH, *args, **kwargs):
        self.__filepath = pathlib.Path(filepath)

    @property
    def filepath(self) -> pathlib.Path:
        """Path to configuration file."""
        return self.__filepath
    
    
