import argparse
from paprika_recipe.exceptions import AuthenticationError
from pathlib import Path

import keyring
from yaml import dump

from ..command import BaseCommand
from ..constants import APP_NAME
from ..remote import Remote


class Command(BaseCommand):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("email", type=str)
        parser.add_argument("export_path", type=Path)

    def handle(self) -> None:
        password = keyring.get_password(APP_NAME, self.options.email)

        if not password:
            raise AuthenticationError(
                f"No password stored for {self.options.email}; "
                "store a password for this user using store-password first."
            )

        self.options.export_path.mkdir(parents=True, exist_ok=True)

        remote = Remote(self.options.email, password)

        for recipe in remote:
            with open(
                self.options.export_path / Path(f"{recipe.name}.paprikarecipe.yaml"),
                "w",
            ) as outf:
                dump(recipe.as_dict(), outf)
