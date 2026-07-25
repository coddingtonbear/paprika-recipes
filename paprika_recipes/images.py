"""Turning a photo the user dropped into a vault into what Paprika expects.

Paprika's own app never uploads a photo as-is.  It sends two derived images:
a square thumbnail that becomes the recipe's `photo` -- the image the app
shows in lists, and the one whose bytes `photo_hash` digests -- and a copy of
the picture itself, scaled down to fit a bounding box, that goes into the
recipe's photo gallery as `photo_large`.  We reproduce both here, at the same
sizes the app uses, so that a photo added from a directory is
indistinguishable from one added in the app.

The full-size image is passed through untouched when it already is what we
would have produced -- a JPEG within the size cap, the right way up -- so
that pushing a photo and pulling it back yields the very bytes the user
supplied whenever that is possible at all.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError

from .exceptions import PaprikaUserError

#: The square thumbnail the app uploads as the recipe's `photo`, in pixels.
THUMBNAIL_SIZE: Final = 280

#: The bounding box the app scales the full image into before uploading it.
FULL_SIZE_LIMIT: Final = 2048

#: Matches the visible quality of the app's own uploads closely enough.
JPEG_QUALITY: Final = 85


@dataclass(frozen=True)
class PreparedPhoto:
    """A user's photo, re-cut the way Paprika stores one."""

    #: A square JPEG for the recipe's `photo`; `photo_hash` digests these bytes.
    thumbnail: bytes
    #: The picture itself, as a JPEG no larger than `FULL_SIZE_LIMIT` a side.
    full: bytes


def prepare_photo(data: bytes) -> PreparedPhoto:
    """Cut a photo into the thumbnail and full-size JPEGs Paprika stores.

    Raises `PaprikaUserError` for bytes that are not a readable image.
    """
    try:
        with Image.open(io.BytesIO(data)) as source:
            # EXIF orientation 1 is "already the right way up"; anything else
            # means the pixels are stored rotated and the tag says how.
            sideways = source.getexif().get(0x0112, 1) != 1
            untouched = (
                source.format == "JPEG"
                and not sideways
                and max(source.size) <= FULL_SIZE_LIMIT
            )

            image = ImageOps.exif_transpose(source) if sideways else source
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise PaprikaUserError(f"it could not be read as an image ({e})")

    return PreparedPhoto(
        thumbnail=_encode(ImageOps.fit(image, (THUMBNAIL_SIZE, THUMBNAIL_SIZE))),
        full=data if untouched else _encode(_fit_within(image, FULL_SIZE_LIMIT)),
    )


def _fit_within(image: Image.Image, limit: int) -> Image.Image:
    """Scale an image down (never up) to fit inside a `limit`-sized square."""
    if max(image.size) <= limit:
        return image

    scaled = image.copy()
    scaled.thumbnail((limit, limit))

    return scaled


def _encode(image: Image.Image) -> bytes:
    """Encode as JPEG, flattening any transparency onto white first."""
    if image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image.convert("RGBA"), mask=image.convert("RGBA"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY)

    return out.getvalue()
