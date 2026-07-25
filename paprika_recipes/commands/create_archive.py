import argparse
from pathlib import Path

from rich.progress import track

from ..archive import Archive, ArchiveRecipe, attach_photo, identify
from ..command import BaseCommand
from ..exceptions import PaprikaUserError
from ..repository import read_recipe, recipe_files


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Creates a new .paprikarecipes file from a directory
        of recipes."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("export_path", type=Path)
        parser.add_argument("archive_path", type=Path)

    def handle(self) -> None:
        archive = Archive()

        # Recipes may have been sorted into folders since they were extracted,
        # and this may well be a directory that `clone` made, so the search is
        # recursive and skips our own bookkeeping.
        paths = list(recipe_files(self.options.export_path))

        if not paths:
            raise PaprikaUserError(
                f"No recipe files were found in {self.options.export_path}."
            )

        for path in track(paths, description="Packing recipes"):
            recipe = identify(read_recipe(path, ArchiveRecipe))
            archive.add_recipe(attach_photo(recipe, path))

        with open(self.options.archive_path, "wb") as outf:
            archive.as_paprikarecipes(outf)
