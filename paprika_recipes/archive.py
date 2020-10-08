from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, List, Iterable, Optional
from zipfile import ZipFile, ZIP_DEFLATED

from .recipe import BaseRecipe
from .types import RecipeManager, UNKNOWN


@dataclass
class ArchiveRecipe(BaseRecipe):
    photos: List[UNKNOWN] = field(default_factory=list)
    photo_data: Optional[str] = None


class Archive(RecipeManager):
    _recipes: List[ArchiveRecipe] = []

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
                archive.add_recipe(
                    ArchiveRecipe.from_file(zip_file.open(zip_info.filename))
                )

        return archive

    def add_recipe(self, recipe: ArchiveRecipe) -> ArchiveRecipe:
        self._recipes.append(recipe)

        return recipe

    def as_paprikarecipes(self, outf: IO[bytes]):
        with ZipFile(outf, mode="w", compression=ZIP_DEFLATED) as zip_file:
            for recipe in self:
                with zip_file.open(
                    f"{recipe.name}.paprikarecipe", mode="w"
                ) as recipe_file:
                    recipe_file.write(recipe.as_paprikarecipe())

    def __str__(self):
        return f"Paprika Archive ({self.count()} recipes)"
