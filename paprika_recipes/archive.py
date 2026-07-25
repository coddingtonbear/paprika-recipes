from __future__ import annotations

import uuid
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from collections.abc import Container, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import IO, Final, TypeVar
from zipfile import ZIP_DEFLATED, ZipFile

from .markdown import ATTACHMENTS_DIRNAME
from .recipe import BaseRecipe
from .types import UNKNOWN, RecipeManager

T = TypeVar("T", bound=BaseRecipe)


@dataclass
class ArchiveRecipe(BaseRecipe):
    photos: list[UNKNOWN] = field(default_factory=list)
    photo_data: str | None = None


#: Recognised by their first few bytes, so that a photo lands with a suffix
#: that matches what it actually is.  Paprika's own exports are JPEG.
PHOTO_SIGNATURES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"RIFF", ".webp"),
)
DEFAULT_PHOTO_SUFFIX: Final = ".jpg"

#: The suffix Paprika gives each recipe inside a `.paprikarecipes` archive.
RECIPE_SUFFIX: Final = ".paprikarecipe"


def detach_photo(recipe: ArchiveRecipe, path: Path) -> ArchiveRecipe:
    """Write a recipe's photo into `attachments/`, and point the recipe at it.

    An archive carries its photos inline, base64-encoded.  That is fine for a
    zip file and hopeless for a text file you intend to read: a single recipe
    would bury its own ingredients under a megabyte of base64.  So the image
    is written to the `attachments/` folder beside the recipe as an ordinary
    image file -- the same place a cloned directory keeps its photos, which
    is what lets the recipe's own markdown embed point at it.
    """
    if not recipe.photo_data:
        return recipe

    try:
        image = b64decode(recipe.photo_data, validate=True)
    except BinasciiError:
        # Not something we can write out as an image.  Leaving it inline is
        # ugly, but it is the recipe's data and losing it would be worse.
        return recipe

    photo = path.parent / ATTACHMENTS_DIRNAME / (path.stem + _photo_suffix(image))
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(image)

    return replace(recipe, photo=photo.name, photo_data=None)


def attach_photo(recipe: ArchiveRecipe, path: Path) -> ArchiveRecipe:
    """Read back a photo that was written out for a recipe file."""
    if recipe.photo_data or not recipe.photo:
        return recipe

    photo = path.parent / ATTACHMENTS_DIRNAME / recipe.photo

    if not photo.is_file():
        # Extractions from before photos moved into `attachments/` left the
        # image directly beside the recipe file.
        photo = path.parent / recipe.photo

    if not photo.is_file():
        return recipe

    return replace(recipe, photo_data=b64encode(photo.read_bytes()).decode("ascii"))


def identify(recipe: T) -> T:
    """Give a recipe a uid of its own if it does not already have one.

    A recipe file somebody wrote by hand has no uid until it is sent
    somewhere -- and an archive is somewhere.  Paprika tracks what it imports
    by uid, so packing a recipe without one leaves the app to invent one, or
    to decide that several such recipes are all the same recipe.
    """
    if recipe.uid:
        return recipe

    return replace(recipe, uid=str(uuid.uuid4()).upper())


def _entry_name(recipe: BaseRecipe, used: Container[str]) -> str:
    """Name a recipe's entry in the archive, distinctly from the others.

    Paprika names each entry after its recipe, which collides whenever two
    recipes share a title.  We disambiguate rather than emit an archive whose
    entries cannot be told apart.
    """
    stem = recipe.name or recipe.uid
    name = f"{stem}{RECIPE_SUFFIX}"

    if name not in used:
        return name

    return f"{stem} ({recipe.uid.split('-')[0]}){RECIPE_SUFFIX}"


def _photo_suffix(image: bytes) -> str:
    for signature, suffix in PHOTO_SIGNATURES:
        if image.startswith(signature):
            return suffix

    return DEFAULT_PHOTO_SUFFIX


class Archive(RecipeManager):
    _recipes: list[ArchiveRecipe]

    def __init__(self):
        self._recipes = []

    @property
    def recipes(self) -> Iterable[ArchiveRecipe]:
        return self._recipes

    def count(self) -> int:
        return len(self._recipes)

    @classmethod
    def from_file(cls, data: IO[bytes]) -> Archive:
        archive = cls()

        with ZipFile(data) as zip_file:
            for zip_info in zip_file.infolist():
                # Opened by entry rather than by name: two recipes sharing a
                # title produce two entries sharing a name, and opening by
                # name would hand back the same one every time -- quietly
                # replacing one of the recipes with a copy of the other.
                archive.add_recipe(ArchiveRecipe.from_file(zip_file.open(zip_info)))

        return archive

    def add_recipe(self, recipe: ArchiveRecipe) -> ArchiveRecipe:
        self._recipes.append(recipe)

        return recipe

    def as_paprikarecipes(self, outf: IO[bytes]):
        used: set[str] = set()

        with ZipFile(outf, mode="w", compression=ZIP_DEFLATED) as zip_file:
            for recipe in self:
                name = _entry_name(recipe, used)
                used.add(name)

                with zip_file.open(name, mode="w") as recipe_file:
                    recipe_file.write(recipe.as_paprikarecipe())

    def __str__(self):
        return f"Paprika Archive ({self.count()} recipes)"
