import os
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any, List, TypeVar, cast

import keyring
import yaml
from appdirs import user_config_dir

from .constants import APP_NAME
from .exceptions import AuthenticationError, PaprikaUserError
from .types import ConfigDict

if TYPE_CHECKING:
    from .recipe import BaseRecipe  # noqa


def str_representer(dumper, data):
    if len(data.splitlines()) > 1:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def ordereddict_representer(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode("tag:yaml.org,2002:map", value)


yaml.add_representer(OrderedDict, ordereddict_representer)

yaml.add_representer(str, str_representer)


def dump_recipe_yaml(recipe: "BaseRecipe", *args: Any):
    key_ordering: List[str] = [
        "name",
        "description",
        "ingredients",
        "directions",
        "notes",
        "nutritional_info",
    ]
    recipe_dict = OrderedDict()
    recipe_dict_unsorted = recipe.as_dict()

    for key in key_ordering:
        if key in recipe_dict_unsorted:
            recipe_dict[key] = recipe_dict_unsorted.pop(key)

    for key in sorted(recipe_dict_unsorted.keys()):
        recipe_dict[key] = recipe_dict_unsorted.pop(key)

    assert not recipe_dict_unsorted

    dump_yaml(recipe_dict, *args)


def dump_yaml(*args: Any):
    # We're using a custom presenter, so we have to use `yaml.dump`
    # instead of `yaml.safe_dump` -- that's OK, though -- we still use
    # `safe_load`, which is where the actual risks are.
    yaml.dump(*args, allow_unicode=True)


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
        outf.write(
            dedent(
                """\
            # Please modify your recipe below, then save and exit.
            # To cancel, delete all content from this file.
        """
            )
        )

        dump_recipe_yaml(recipe, outf)

        outf.seek(0)

        proc = subprocess.Popen([editor, outf.name])
        proc.wait()

        outf.seek(0)

        contents = outf.read().strip()

        if not contents:
            raise PaprikaUserError("Empty recipe found; aborting")

        outf.seek(0)

        return recipe.__class__.from_dict(yaml.safe_load(outf))


def get_config_dir() -> Path:
    root_path = Path(user_config_dir(APP_NAME, "coddingtonbear"))
    os.makedirs(root_path, exist_ok=True)

    return root_path


def get_cache_dir() -> Path:
    cache_path = Path(user_config_dir(APP_NAME, "coddingtonbear")) / "cache"
    os.makedirs(cache_path, exist_ok=True)

    return cache_path


def get_default_config_path() -> Path:
    root_path = get_config_dir()
    return root_path / "config.yaml"


def get_config(path: Path = None) -> ConfigDict:
    if path is None:
        path = get_default_config_path()

    if not os.path.isfile(path):
        return {}

    with open(path, "r") as inf:
        return cast(ConfigDict, load_yaml(inf))


def save_config(data: ConfigDict, path: Path = None) -> None:
    if path is None:
        path = get_default_config_path()

    with open(path, "w") as outf:
        dump_yaml(data, outf)
