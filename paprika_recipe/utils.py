from typing import Any

import keyring
import yaml

from .constants import APP_NAME
from .exceptions import AuthenticationError


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
