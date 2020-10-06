import argparse
from pathlib import Path

from yaml import dump

from ..archive import Archive
from ..command import BaseCommand


class Command(BaseCommand):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("archive_path", type=Path)
        parser.add_argument("export_path", type=Path)

    def handle(self) -> None:
        with open(self.options.archive_path, "rb") as inf:
            archive = Archive.from_file(inf)

            self.options.export_path.mkdir(parents=True, exist_ok=True)

            for recipe in archive.recipes:
                with open(
                    self.options.export_path
                    / Path(f"{recipe.name}.paprikarecipe.yaml"),
                    "w",
                ) as outf:
                    dump(recipe.as_dict(), outf)
