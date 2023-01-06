import argparse
from pathlib import Path
import os
import urllib

from rich.progress import track

from ..command import RemoteCommand
from ..types import ConfigDict
from ..utils import dump_recipe_yaml


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Downloads all recipes from a paprika account to a directory."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("export_path", type=Path)
        parser.add_argument(
            "--download-images",
            default=False,
            type=bool,
            help="Downloads images attached to the recipes",
        )

    def handle(self) -> None:
        remote = self.get_remote()

        self.options.export_path.mkdir(parents=True, exist_ok=True)

        for recipe in track(
            remote, total=remote.count(), description="Downloading Recipes"
        ):
            if self.options.download_images:
                images_path = self.options.export_path / "images"
                images_path.mkdir(parents=True, exist_ok=True)

                image = remote.fetch_recipe_image(recipe)
                if image is not None:
                    file_extension = os.path.splitext(recipe.photo)[1]
                    destination_path = images_path / f"{recipe.uid}{file_extension}"

                    file = open(destination_path, "wb")
                    file.write(image)
                    file.close()

                    recipe.local_image_url = destination_path.relative_to(
                        self.options.export_path
                    ).as_posix()

            with open(
                self.options.export_path / Path(f"{recipe.name}.paprikarecipe.yaml"),
                "w",
            ) as outf:
                dump_recipe_yaml(recipe, outf)
