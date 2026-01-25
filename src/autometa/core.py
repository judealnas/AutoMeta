import base64
import mimetypes
import typing
from pathlib import Path

from mutagen import File, FileType
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, Frames

import autometa.tags
from autometa.types import FileTypes, PathLike


class MusicFile:
    def __init__(self, file: PathLike):
        self._path = Path(file)
        self._file: FileType = File(file)
        self._file_type = type(self._file)

        ext = self._path.suffix.lower().lstrip(".")
        self._tag_map = autometa.tags.get_tag_map(ext)
        self._ext = ext

    @property
    def path(self) -> Path:
        return self._path

    @property
    def file_type(self):
        return self._file_type

    def __getitem__(
        self, tag: str | autometa.tags.Tags
    ) -> typing.Union[str, list[str], None]:
        """Get a tag value. Returns None if tag doesn't exist.

        For FLAC files with multiple values, returns a list.
        For FLAC files with single value, returns a string.
        For MP3 files, always returns a string or None.
        """
        if isinstance(tag, autometa.tags.Tags):
            mapped_tag = self._tag_map[tag.value]
        else:
            mapped_tag = self._tag_map[tag]

        # Handle different file types
        if self._ext in (FileTypes.FLAC, FileTypes.OGG):
            # FLAC/OGG use Vorbis Comments which support multiple values
            values = self._file.get(mapped_tag, [])
            if not values:
                return None
            # Return single value as string, multiple values as list
            return values[0] if len(values) == 1 else values
        else:  # MP3
            frame = self._file.get(mapped_tag)
            if frame is None:
                return None
            # ID3 frames have a 'text' attribute
            if hasattr(frame, "text"):
                return str(frame.text[0]) if frame.text else None
            return str(frame)

    def __setitem__(
        self,
        tag: str | autometa.tags.Tags,
        value: typing.Union[str, list[str]],
    ) -> None:
        """Set a tag value.

        For FLAC files: accepts string or list of strings for multiple values.
        For MP3 files: accepts string or list (list will be joined with '; ').
        """
        if isinstance(tag, autometa.tags.Tags):
            mapped_tag = self._tag_map[tag.value]
        else:
            mapped_tag = self._tag_map[tag]

        # Handle different file types
        if self._ext in (FileTypes.FLAC, FileTypes.OGG):
            # FLAC/OGG accept lists directly
            if isinstance(value, list):
                self._file[mapped_tag] = value
            else:
                self._file[mapped_tag] = [value]
        else:  # MP3
            # MP3 ID3 frames need proper frame classes
            frame_class = Frames.get(mapped_tag)

            if frame_class is None:
                # Fallback for unknown frames
                self._file[mapped_tag] = value
            else:
                # Handle multiple values by joining with semicolon
                if isinstance(value, list):
                    value = "; ".join(value)

                # Create the appropriate ID3 frame
                # encoding=3 is UTF-8
                self._file[mapped_tag] = frame_class(encoding=3, text=value)

    def add_picture(
        self,
        image_path: PathLike,
        mime_type: str | None = None,
        picture_type: int = 3,
        description: str = "",
    ) -> None:
        """Add a picture/album art to the file.

        Args:
            image_path: Path to the image file
            mime_type: MIME type of the image (auto-detected from file if not provided)
            picture_type: Type of picture (default: 3 = front cover)
                For common types:
                - 3: Front cover
                - 4: Back cover
                - 0: Other
                - 1: 32x32 pixels file icon
                - 2: Other file icon
            description: Optional description of the picture
        """
        with open(image_path, "rb") as img_file:
            image_data = img_file.read()

        # Auto-detect MIME type if not provided
        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type is None or not mime_type.startswith("image/"):
                # Fallback to JPEG if detection fails
                mime_type = "image/jpeg"

        if self._ext in (FileTypes.FLAC, FileTypes.OGG):
            # FLAC uses Picture objects
            picture = Picture()
            picture.data = image_data
            picture.type = picture_type
            picture.mime = mime_type
            picture.desc = description

            # Detect dimensions if possible
            try:
                import io

                from PIL import Image  # type: ignore

                img = Image.open(io.BytesIO(image_data))
                picture.width, picture.height = img.size
                picture.depth = img.mode == "RGB" and 24 or 32  # Simplified
            except (ImportError, OSError, ValueError):
                # PIL not available or error reading image, skip dimensions
                pass

            if isinstance(self._file, FLAC):
                self._file.add_picture(picture)
            else:  # OGG Vorbis
                pic_data = picture.write()
                vcomment_value = base64.b64encode(pic_data).decode("ascii")
                self._file["metadata_block_picture"] = [vcomment_value]

        else:  # MP3
            # MP3 uses APIC frames
            self._file["APIC"] = APIC(
                encoding=3,  # UTF-8
                mime=mime_type,
                type=picture_type,
                desc=description,
                data=image_data,
            )

    def save(self) -> None:
        """Save changes to the file."""
        self._file.save()
