from autometa.tags import Tags
from mutagen.easyid3 import EasyID3
from mutagen.id3 import COMM


EasyID3.RegisterTextKey("comment", COMM().FrameID)

easyid3_tag_map = {
    Tags.TITLE: "title",
    Tags.ALBUM: "album",
    Tags.ARTIST: "artist",
    Tags.AUTHOR: "author",
    Tags.GENRE: "genre",
    Tags.COMMENT: "comment",
    Tags.YEAR: "date",
    Tags.TRACK: "tracknumber",
}
