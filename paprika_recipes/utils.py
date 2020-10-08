import subprocess
import tempfile
from typing import Any, TypeVar, TYPE_CHECKING

import keyring
import yaml

from .constants import APP_NAME
from .exceptions import AuthenticationError, PaprikaUserError

if TYPE_CHECKING:
    from .recipe import BaseRecipe  # noqa


def str_presenter(dumper, data):
    if len(data.splitlines()) > 1:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)


def dump_yaml(*args: Any):
    yaml.dump(*args, allow_unicode=True)


def get_password_for_email(email: str) -> str:
    password = keyring.get_password(APP_NAME, email)

    if not password:
        raise AuthenticationError(
            f"No password stored for {email}; "
            "store a password for this user using store-password first."
        )

    return password


T = TypeVar("T", bound="BaseRecipe")


def edit_recipe_interactively(recipe: T, editor="vim") -> T:
    with tempfile.NamedTemporaryFile(suffix=".paprikarecipe.yaml", mode="w+") as outf:

        dump_yaml(recipe.as_dict(), outf)

        outf.seek(0)

        proc = subprocess.Popen([editor, outf.name])
        proc.wait()

        outf.seek(0)

        contents = outf.read().strip()

        if not contents:
            raise PaprikaUserError("Empty recipe found; aborting")

        outf.seek(0)

        return recipe.__class__.from_dict(yaml.safe_load(outf))
