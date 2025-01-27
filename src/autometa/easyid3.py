from autometa.tags import Tags
from mutagen.easyid3 import EasyID3
from mutagen.id3 import COMM

# TODO: Use mutagen RegisterKey to add support for COMM (ID3 comment) frames
easyid3_tag_map = {
    Tags.TITLE: "title",
    Tags.ALBUM: "album",
    Tags.ARTIST: "artist",
    Tags.AUTHOR: "author",
    Tags.GENRE: "genre",
    # Tags.COMMENT: "comment",
    Tags.YEAR: "date",
}
