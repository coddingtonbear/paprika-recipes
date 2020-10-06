import argparse
from pathlib import Path

from yaml import safe_load

from ..archive import Archive
from ..recipe import Recipe
from ..command import BaseCommand


class Command(BaseCommand):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("export_path", type=Path)
        parser.add_argument("archive_path", type=Path)

    def handle(self) -> None:
        archive = Archive()

        for recipe_file in self.options.export_path.iterdir():
            with open(recipe_file, "r") as inf:
                archive.add_recipe(Recipe.from_dict(safe_load(inf)))

        with open(self.options.archive_path, "wb") as outf:
            archive.as_paprikarecipes(outf)
