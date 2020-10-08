import argparse
import os
import subprocess
import tempfile

from yaml import safe_load

from ..command import BaseCommand
from ..exceptions import PaprikaUserError
from ..remote import Remote, RemoteRecipe
from ..utils import dump_yaml, get_password_for_email


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
        archive = Remote(self.options.email, password)

        with tempfile.NamedTemporaryFile(
            suffix=".paprikarecipe.yaml", mode="w+"
        ) as outf:
            empty_recipe = RemoteRecipe()

            dump_yaml(empty_recipe.as_dict(), outf)

            outf.seek(0)

            proc = subprocess.Popen([self.options.editor, outf.name])
            proc.wait()

            outf.seek(0)

            contents = outf.read().strip()

            if not contents:
                raise PaprikaUserError("Empty recipe found; aborting")

            outf.seek(0)

            recipe = RemoteRecipe.from_dict(safe_load(outf))
            archive.upload_recipe(recipe)
            archive.notify()
