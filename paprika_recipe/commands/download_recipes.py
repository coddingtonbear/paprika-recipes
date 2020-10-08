import argparse
from pathlib import Path

import keyring

from ..command import BaseCommand
from ..constants import APP_NAME
from ..exceptions import AuthenticationError
from ..remote import Remote
from ..utils import dump_yaml


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Downloads all recipes from a paprika account to a directory."""

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
                dump_yaml(recipe.as_dict(), outf)
