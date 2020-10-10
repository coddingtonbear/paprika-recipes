import argparse
import os

from ..command import RemoteCommand
from ..remote import RemoteRecipe
from ..types import ConfigDict
from ..utils import edit_recipe_interactively


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Opens an editor allowing you to upload a new paprika recipe."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("--editor", default=os.environ.get("EDITOR", "vim"))

    def handle(self) -> None:
        remote = self.get_remote()

        created = edit_recipe_interactively(RemoteRecipe())

        remote.upload_recipe(created)
        remote.notify()
