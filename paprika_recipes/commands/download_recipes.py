import argparse
from pathlib import Path

from rich.progress import track

from ..command import RemoteCommand
from ..types import ConfigDict
from ..utils import dump_yaml


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Downloads all recipes from a paprika account to a directory."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("export_path", type=Path)
        parser.add_argument(
            "--download_images",
            default=False,
            type=bool,
            help="Allows to download every image attached to the recipes",
        )

    def handle(self) -> None:
        remote = self.get_remote()

        self.options.export_path.mkdir(parents=True, exist_ok=True)

        for recipe in track(
            remote, total=remote.count(), description="Downloading Recipes"
        ):
            if self.options.download_images:
                remote.download_image(recipe)
            with open(
                self.options.export_path / Path(f"{recipe.name}.paprikarecipe.yaml"),
                "w",
            ) as outf:
                dump_yaml(recipe.as_dict(), outf)
