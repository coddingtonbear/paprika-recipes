import argparse
import os

from ..command import BaseCommand
from ..remote import Remote, RemoteRecipe
from ..utils import get_password_for_email, edit_recipe_interactively


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Opens an editor allowing you to upload a new paprika recipe."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--editor", default=os.environ.get("EDITOR", "vim"))
        parser.add_argument("email", type=str)

    def handle(self) -> None:
        password = get_password_for_email(self.options.email)
        remote = Remote(self.options.email, password)

        created = edit_recipe_interactively(RemoteRecipe())

        remote.upload_recipe(created)
        remote.notify()
