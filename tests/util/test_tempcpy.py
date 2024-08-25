import os
import tempfile
import unittest

from autometa.util.tempcpy import TemporaryCopy


class TemporaryCopyTestCase(unittest.TestCase):

    def test_temp_txt(self):
        """Test creating a temporary copy of TXT files."""
        # Create a temporary file to temporarily copy
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w+") as temp_file:
            temp_file.write("Hello, world!")

            # Create a temporary copy of the file
            with TemporaryCopy(temp_file.name) as temp_copy:
                content = temp_copy.read()
                self.assertEqual(content, "Hello, world!")


if __name__ == "__main__":
    unittest.main()
