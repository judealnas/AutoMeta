import os
import pathlib
import shutil
import tempfile
from typing import Union

PATH = Union[str, bytes, os.PathLike]


class TemporaryCopy:
    """Create a temporary copy of a file.

    :param src: The path to the source file to be copied.
    :type src: typing.Union[str, bytes, os.PathLike]
    :param **kwargs: Additional arguments to pass to tempfile.TemporaryDirectory.


    :Example:

    Create a temporary copy of "example.txt" and use the temporary file:

    .. code-block:: python

        with TemporaryCopy("example.txt") as temp_cpy:
            with open(temp_cpy) as f:
                content = f.read()

    The temporary file is automatically deleted after the context exits.

    .. seealso:: `tempfile.TemporaryDirectory <https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory>`_
    """

    def __init__(self, src: PATH, **kwargs):
        # Check if the source file exists and is a file
        self._src = pathlib.Path(src)
        if not self._src.exists():
            raise FileNotFoundError(f"Source file does not exist: {self._src}")
        if not self._src.is_file():
            raise IsADirectoryError(f"Source path is not a file: {self._src}")

        self._tempdir = tempfile.TemporaryDirectory(**kwargs)
        self._path = pathlib.Path(self._tempdir.name, self._src.name)
        self._file = None

        # Save kwargs for repr
        self._kwargs = kwargs

    @property
    def src(self):
        """The source file path to copy."""
        return self._src

    @src.setter
    def src(self, src: PATH):
        self._src = pathlib.Path(src)
        self._path = pathlib.Path(self._tempdir.name, self._src.name)

    def __enter__(self):
        # Copy the file to the temporary directory, returning the resulting path
        return pathlib.Path(shutil.copy2(self._src, self._path))

    def __exit__(self, exc_type, exc_value, exc_traceback):
        # Cleanup the temporary directory, deleting the copy in the process
        self._tempdir.cleanup()

    def __fspath__(self):
        """Return the path to the temporary copy."""
        return os.fspath(self._path)

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self):
        _repr = f"{self.__class__.__name__}(src={self.src!r}"
        if self._kwargs:
            for key, value in self._kwargs.items():
                _repr += f", {key}={value!r}"

        return _repr + ")"
