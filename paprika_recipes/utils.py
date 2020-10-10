import os
import subprocess
import tempfile
from typing import Any, cast, TypeVar, TYPE_CHECKING

from appdirs import user_config_dir
import keyring
import yaml

from .constants import APP_NAME
from .exceptions import AuthenticationError, PaprikaUserError
from .types import ConfigDict

if TYPE_CHECKING:
    from .recipe import BaseRecipe  # noqa


def str_presenter(dumper, data):
    if len(data.splitlines()) > 1:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)


def dump_yaml(*args: Any):
    yaml.safe_dump(*args, allow_unicode=True)


def load_yaml(*args: Any) -> Any:
    return yaml.safe_load(*args)


def get_password_for_email(email: str) -> str:
    if not email:
        raise AuthenticationError("No account was specified.")

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


def get_config_dir() -> str:
    root_path = user_config_dir(APP_NAME, "coddingtonbear")
    os.makedirs(root_path, exist_ok=True)

    return root_path


def get_default_config_path() -> str:
    root_path = get_config_dir()
    return os.path.join(root_path, "config.yaml",)


def get_config(path: str = None) -> ConfigDict:
    if path is None:
        path = get_default_config_path()

    if not os.path.isfile(path):
        return {}

    with open(path, "r") as inf:
        return cast(ConfigDict, load_yaml(inf))


def save_config(data: ConfigDict, path: str = None) -> None:
    if path is None:
        path = get_default_config_path()

    with open(path, "w") as outf:
        dump_yaml(data, outf)
