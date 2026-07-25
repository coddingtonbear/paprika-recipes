import io

import pytest
from PIL import Image

from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.images import FULL_SIZE_LIMIT, THUMBNAIL_SIZE, prepare_photo


def encode(image: Image.Image, format: str = "JPEG", **options) -> bytes:
    out = io.BytesIO()
    image.save(out, format=format, **options)

    return out.getvalue()


def dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


class TestThumbnails:
    def test_are_square_at_the_size_the_app_uses(self):
        prepared = prepare_photo(encode(Image.new("RGB", (1600, 1200), "red")))

        assert dimensions(prepared.thumbnail) == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)

    def test_even_from_a_tall_original(self):
        prepared = prepare_photo(encode(Image.new("RGB", (600, 2400), "red")))

        assert dimensions(prepared.thumbnail) == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)

    def test_are_jpegs(self):
        prepared = prepare_photo(encode(Image.new("RGB", (500, 500), "red"), "PNG"))

        with Image.open(io.BytesIO(prepared.thumbnail)) as image:
            assert image.format == "JPEG"


class TestTheFullSizeImage:
    def test_a_modest_jpeg_passes_through_byte_for_byte(self):
        """Pushing a photo and pulling it back should return the user's own
        bytes whenever nothing about them needs changing."""
        data = encode(Image.new("RGB", (1600, 1200), "red"))

        assert prepare_photo(data).full == data

    def test_an_oversized_image_is_scaled_to_the_apps_cap(self):
        prepared = prepare_photo(encode(Image.new("RGB", (4096, 1024), "red")))

        assert dimensions(prepared.full) == (FULL_SIZE_LIMIT, FULL_SIZE_LIMIT // 4)

    def test_a_png_becomes_a_jpeg(self):
        prepared = prepare_photo(encode(Image.new("RGB", (600, 400), "red"), "PNG"))

        with Image.open(io.BytesIO(prepared.full)) as image:
            assert image.format == "JPEG"
            assert image.size == (600, 400)

    def test_transparency_is_flattened_rather_than_fatal(self):
        prepared = prepare_photo(
            encode(Image.new("RGBA", (600, 400), (255, 0, 0, 0)), "PNG")
        )

        with Image.open(io.BytesIO(prepared.full)) as image:
            assert image.mode == "RGB"

    def test_a_sideways_phone_photo_is_stood_upright(self):
        """A camera often stores the pixels rotated and an EXIF tag saying
        so.  Paprika's server will not read the tag for us, so the pixels
        have to be turned before they go up."""
        exif = Image.Exif()
        exif[0x0112] = 6  # "rotate 90 CW to display"
        data = encode(Image.new("RGB", (800, 600), "red"), exif=exif)

        prepared = prepare_photo(data)

        assert prepared.full != data
        assert dimensions(prepared.full) == (600, 800)
        assert dimensions(prepared.thumbnail) == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)


class TestUnreadableImages:
    @pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff\xe0 nope"])
    def test_are_refused_with_a_reason(self, data):
        with pytest.raises(PaprikaUserError, match="could not be read as an image"):
            prepare_photo(data)
