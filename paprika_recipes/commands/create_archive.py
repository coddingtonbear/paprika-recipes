import argparse
from pathlib import Path

from yaml import safe_load

from ..archive import Archive, ArchiveRecipe
from ..command import BaseCommand
from ..types import ConfigDict


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Creates a new .paprikarecipes file from a directory
        of recipes."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("export_path", type=Path)
        parser.add_argument("archive_path", type=Path)

    def handle(self) -> None:
        archive = Archive()

        for recipe_file in self.options.export_path.iterdir():
            with open(recipe_file, "r") as inf:
                archive.add_recipe(ArchiveRecipe.from_dict(safe_load(inf)))

        with open(self.options.archive_path, "wb") as outf:
            archive.as_paprikarecipes(outf)
