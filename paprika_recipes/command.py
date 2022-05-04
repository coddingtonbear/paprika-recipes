from __future__ import annotations

import argparse
import logging
from abc import ABCMeta, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Type

import pkg_resources

from .cache import Cache, DirectoryCache, NullCache, WriteOnlyDirectoryCache
from .exceptions import PaprikaProgrammingError
from .remote import Remote
from .types import ConfigDict
from .utils import get_cache_dir, get_password_for_email

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
        """Provides options provided at the command-line."""
        return self._options

    @property
    def config(self) -> ConfigDict:
        """Returns saved configuration as a dictionary."""
        return self._config

    @classmethod
    def get_help(cls) -> str:
        """Retuurns help text for this function."""
        return ""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        """Allows adding additional command-line arguments."""
        pass

    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        cls.add_arguments(parser, config)

    @abstractmethod
    def handle(self) -> None:
        """This is where the work of your function starts."""
        ...


class RemoteCommand(BaseCommand):
    _cache: Optional[Cache] = None

    class CacheChoices(Enum):
        none = "none"
        ignore = "ignore"
        enabled = "enabled"

        def __str__(self):
            return self.value

    def get_cache(self) -> Cache:
        if not self._cache:
            if self.options.cache_mode == self.CacheChoices.enabled:
                self._cache = DirectoryCache(self.options.cache_path)
            elif self.options.cache_mode == self.CacheChoices.ignore:
                self._cache = WriteOnlyDirectoryCache(self.options.cache_path)
            elif self.options.cache_mode == self.CacheChoices.none:
                self._cache = NullCache()
            else:
                raise PaprikaProgrammingError(
                    f"Unhandled cache choice: {self.options.cache_mode}"
                )

        return self._cache

    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        """Allows adding additional command-line arguments."""
        parser.add_argument(
            "--account", type=str, default=config.get("default_account", "")
        )
        parser.add_argument(
            "--cache-mode",
            type=cls.CacheChoices,
            choices=cls.CacheChoices,
            default=cls.CacheChoices.enabled,
            help=(
                "enabled (default): read and write from the cache; "
                "ignore: write to the cache, but do not read from it; "
                "none: neither read nor write to the cache."
            ),
        )
        parser.add_argument(
            "--cache-path",
            type=Path,
            default=Path(get_cache_dir()),
            help=f"directory to store cache files within; default: {get_cache_dir()}",
        )
        super()._add_arguments(parser, config)

    def get_remote(self) -> Remote:
        return Remote(
            self.options.account,
            get_password_for_email(self.options.account),
            cache=self.get_cache(),
        )
