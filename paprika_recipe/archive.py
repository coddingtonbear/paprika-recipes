from __future__ import annotations

from typing import IO, List
from zipfile import ZipFile

from .recipe import Recipe


class Archive:
    recipes: List[Recipe] = []

    @classmethod
    def from_file(cls, data: IO) -> Archive:
        archive = cls()

        zip_file = ZipFile(data)

        for zip_info in zip_file.infolist():
            archive.add_recipe(Recipe.from_file(zip_file.open(zip_info.filename)))

        return archive

    def add_recipe(self, recipe: Recipe):
        self.recipes.append(recipe)

    def __str__(self):
        return f"Paprika Archive ({len(self.recipes)} recipes)"

    def __repr__(self):
        return f"<{self}>"
