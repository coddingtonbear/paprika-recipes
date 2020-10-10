from __future__ import annotations

import argparse
from abc import ABCMeta, abstractmethod
import logging
import pkg_resources
from typing import Dict, Type

from .remote import Remote
from .utils import get_password_for_email
from .types import ConfigDict


logger = logging.getLogger(__name__)


def get_installed_commands() -> Dict[str, Type[BaseCommand]]:
    possible_commands: Dict[str, Type[BaseCommand]] = {}
    for entry_point in pkg_resources.iter_entry_points(
        group="paprika_recipes.commands"
    ):
        try:
            loaded_class = entry_point.load()
        except ImportError:
            logger.warning(
                "Attempted to load entrypoint %s, but " "an ImportError occurred.",
                entry_point,
            )
            continue
        if not issubclass(loaded_class, BaseCommand):
            logger.warning(
                "Loaded entrypoint %s, but loaded class is "
                "not a subclass of `paprika_recipes.command.BaseCommand`.",
                entry_point,
            )
            continue
        possible_commands[entry_point.name] = loaded_class

    return possible_commands


class BaseCommand(metaclass=ABCMeta):
    def __init__(self, config: ConfigDict, options: argparse.Namespace):
        self._options: argparse.Namespace = options
        self._config: ConfigDict = config
        super().__init__()

    @property
    def options(self) -> argparse.Namespace:
        """ Provides options provided at the command-line."""
        return self._options

    @property
    def config(self) -> ConfigDict:
        """ Returns saved configuration as a dictionary."""
        return self._config

    @classmethod
    def get_help(cls) -> str:
        """ Retuurns help text for this function."""
        return ""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        """ Allows adding additional command-line arguments. """
        pass

    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        cls.add_arguments(parser, config)

    @abstractmethod
    def handle(self) -> None:
        """ This is where the work of your function starts. """
        ...


class RemoteCommand(BaseCommand):
    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        """ Allows adding additional command-line arguments. """
        parser.add_argument(
            "--account", type=str, default=config.get("default_account", "")
        )
        super()._add_arguments(parser, config)

    def get_remote(self) -> Remote:
        return Remote(
            self.options.account, get_password_for_email(self.options.account)
        )
