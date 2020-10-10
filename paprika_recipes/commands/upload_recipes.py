import argparse
from pathlib import Path

from rich.progress import track
from yaml import safe_load

from ..remote import RemoteRecipe
from ..command import RemoteCommand
from ..types import ConfigDict
from ..utils import dump_yaml


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Uploads a directory of recipes to a paprika account."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("import_path", type=Path)

    def handle(self) -> None:
        remote = self.get_remote()

        files = list(self.options.import_path.iterdir())

        for recipe_file in track(files, description="Uploading Recipes"):
            with open(recipe_file, "r") as inf:
                uploaded = remote.upload_recipe(RemoteRecipe.from_dict(safe_load(inf)))

            with open(recipe_file, "w") as outf:
                dump_yaml(uploaded.as_dict(), outf)

        remote.notify()
