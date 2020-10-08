import argparse
from pathlib import Path

import keyring
from yaml import safe_load

from ..constants import APP_NAME
from ..remote import Remote, RemoteRecipe
from ..command import BaseCommand
from ..utils import dump_yaml


class Command(BaseCommand):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("email", type=str)
        parser.add_argument("import_path", type=Path)

    def handle(self) -> None:
        password = keyring.get_password(APP_NAME, self.options.email)
        archive = Remote(self.options.email, password)

        for recipe_file in self.options.import_path.iterdir():
            with open(recipe_file, "r") as inf:
                uploaded = archive.upload_recipe(RemoteRecipe.from_dict(safe_load(inf)))

            with open(recipe_file, "w") as outf:
                dump_yaml(uploaded.as_dict(), outf)

        archive.notify()
