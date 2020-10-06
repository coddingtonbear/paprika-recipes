from __future__ import annotations

import gzip
import json
from typing import IO, List
from zipfile import ZipFile, ZIP_DEFLATED

from .recipe import Recipe


class Archive:
    recipes: List[Recipe] = []

    @classmethod
    def from_file(cls, data: IO[bytes]) -> Archive:
        archive = cls()

        with ZipFile(data) as zip_file:
            for zip_info in zip_file.infolist():
                archive.add_recipe(Recipe.from_file(zip_file.open(zip_info.filename)))

        return archive

    def add_recipe(self, recipe: Recipe):
        self.recipes.append(recipe)

    def as_paprikarecipes(self, outf: IO[bytes]):
        with ZipFile(outf, mode="w", compression=ZIP_DEFLATED) as zip_file:
            for recipe in self.recipes:
                with zip_file.open(
                    f"{recipe.name}.paprikarecipe", mode="w"
                ) as recipe_file:
                    with gzip.open(recipe_file, mode="wb") as recipe_file_gz:
                        recipe_file_gz.write(
                            json.dumps(recipe.as_dict()).encode("utf-8")
                        )

    def __str__(self):
        return f"Paprika Archive ({len(self.recipes)} recipes)"

    def __repr__(self):
        return f"<{self}>"
