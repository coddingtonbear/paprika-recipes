import argparse
from pathlib import Path

from ..archive import Archive
from ..command import BaseCommand
from ..types import ConfigDict
from ..utils import dump_yaml


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Extracts a .paprikarecipes archive to a directory."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("archive_path", type=Path)
        parser.add_argument("export_path", type=Path)

    def handle(self) -> None:
        with open(self.options.archive_path, "rb") as inf:
            archive = Archive.from_file(inf)

            self.options.export_path.mkdir(parents=True, exist_ok=True)

            for recipe in archive:
                with open(
                    self.options.export_path
                    / Path(f"{recipe.name}.paprikarecipe.yaml"),
                    "w",
                ) as outf:
                    dump_yaml(recipe.as_dict(), outf)
