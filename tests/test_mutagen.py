import unittest

class MutagenTestCase(unittest.TestCase):
    def test_mutagen(self):
        from mutagen.mp3 import MP3
        audio = MP3('test.mp3')
        self.assertEqual(audio.info.length, 60)