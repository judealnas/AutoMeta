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
    :param mode: The file access mode. Defaults to 'r+b' (read and write in binary mode).
    :type mode: str
    :param **kwargs: Additional arguments to pass to tempfile.TemporaryDirectory.

    :returns: The file object for the temporary file.
    :rtype: typing.IO

    :Example:

    Create a temporary copy of "example.txt" and use the temporary file:

    .. code-block:: python

        with TemporaryCopy("example.txt") as temp_file:
            content = temp_file.read()

    The temporary file is automatically deleted after the context exits.

    .. seealso:: `tempfile.TemporaryDirectory <https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory>`_
    """

    def __init__(self, src: PATH, mode: str = "r+b", **kwargs):
        self.src = pathlib.Path(src)
        self.mode = mode
        self.temp_dir = tempfile.TemporaryDirectory(**kwargs)
        self.file_path = os.path.join(self.temp_dir.name, self.src.name)
        self.file = None

    def __enter__(self):
        # Copy the file to the temporary directory
        shutil.copy2(self.src, self.file_path)
        # Open the temporary file with the specified mode and store the file object
        self.file = open(self.file_path, self.mode)
        return self.file

    def __exit__(self, exc_type, exc_value, exc_traceback):
        # Close the file object if it's open
        if self.file:
            self.file.close()
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    def __getattr__(self, attr):
        """Delegate attribute access to the file object."""
        return getattr(self.file, attr)

    def __iter__(self):
        """Allow iteration over lines in the file."""
        return iter(self.file)


# Example usage
if __name__ == "__main__":
    text = "Hello, World!"
    with open("example.txt", "w") as file:
        file.write(text)

    tc = TemporaryCopy("example.txt", mode="r")
    with tc as temp_file:
        content = temp_file.read()
        assert content == text, "Content does not match"

    assert not os.path.exists(tc.file_path), "Temporary file still exists"
    assert not os.path.exists(tc.temp_dir.name), "Temporary directory still exists"
# The temporary file and directory are cleaned up after exiting the block.
