import os
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from appdirs import user_config_dir

from .constants import APP_NAME

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
    key_ordering: list[str] = [
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


def get_cache_dir() -> Path:
    cache_path = Path(user_config_dir(APP_NAME, "coddingtonbear")) / "cache"
    os.makedirs(cache_path, exist_ok=True)

    return cache_path
