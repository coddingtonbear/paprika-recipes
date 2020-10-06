from __future__ import annotations

import argparse
from abc import ABCMeta, abstractmethod
import logging
import pkg_resources
from typing import Dict, Type


logger = logging.getLogger(__name__)


def get_installed_commands() -> Dict[str, Type[BaseCommand]]:
    possible_commands: Dict[str, Type[BaseCommand]] = {}
    for entry_point in pkg_resources.iter_entry_points(group="paprika_recipe.commands"):
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
                "not a subclass of `paprika_recipe.command.BaseCommand`.",
                entry_point,
            )
            continue
        possible_commands[entry_point.name] = loaded_class

    return possible_commands


class BaseCommand(metaclass=ABCMeta):
    def __init__(self, options: argparse.Namespace):
        self._options: argparse.Namespace = options
        super().__init__()

    @property
    def options(self) -> argparse.Namespace:
        """ Provides options provided at the command-line."""
        return self._options

    @classmethod
    def get_help(cls) -> str:
        """ Retuurns help text for this function."""
        return ""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """ Allows adding additional command-line arguments. """
        pass

    @abstractmethod
    def handle(self) -> None:
        """ This is where the work of your function starts. """
        ...
