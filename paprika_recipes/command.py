from __future__ import annotations

import argparse
import logging
from abc import ABCMeta, abstractmethod
from enum import Enum
from importlib.metadata import entry_points
from pathlib import Path

from rich.console import Console

from .cache import Cache, DirectoryCache, NullCache, WriteOnlyDirectoryCache
from .constants import DEFAULT_DOMAIN, ExitCode
from .credentials import ask_for_account, authenticate
from .exceptions import PaprikaProgrammingError
from .remote import Remote
from .repository import Repository
from .types import ConfigDict
from .utils import get_cache_dir, save_config

logger = logging.getLogger(__name__)


def get_installed_commands() -> dict[str, type[BaseCommand]]:
    possible_commands: dict[str, type[BaseCommand]] = {}
    for entry_point in entry_points(group="paprika_recipes.commands"):
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
    def add_arguments(  # noqa: B027
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        """Allows adding additional command-line arguments."""

    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        cls.add_arguments(parser, config)

    @abstractmethod
    def handle(self) -> ExitCode | None:
        """This is where the work of your function starts.

        Return an `ExitCode` to say how it went; returning nothing means it
        went fine.  Failures are raised rather than returned -- the exception
        carries the explanation, and `cmdline` turns it into the right code.
        """
        ...


class RemoteCommand(BaseCommand):
    _cache: Cache | None = None
    _account: str = ""

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
            "--account",
            type=str,
            default=None,
            help=(
                "the paprika account to talk to; defaults to the account this "
                "directory was cloned from, or to your default account."
            ),
        )
        parser.add_argument(
            "--domain",
            type=str,
            default=None,
            help=(
                "the host serving paprika's API; only useful for putting a "
                f"proxy in front of it. default: {DEFAULT_DOMAIN}"
            ),
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

    def get_account(self) -> str:
        return self._account or self.options.account or self.default_account()

    def default_account(self) -> str:
        """The account to fall back on when none was named."""
        return self.config.get("default_account", "")

    def get_domain(self) -> str:
        return self.options.domain or DEFAULT_DOMAIN

    def get_remote(self) -> Remote:
        """Connect to an account, asking for whatever we have not been told."""
        console = Console()

        self._account = self.get_account() or ask_for_account(console)

        remote = authenticate(
            self._account, self.get_domain(), self.get_cache(), console
        )

        self.remember_account(self._account)

        return remote

    def remember_account(self, account: str) -> None:
        """Remember the first account we are told about, so we stop asking.

        Only the first: someone with two accounts should not find their
        default quietly reassigned by whichever one they used last.
        """
        if self.config.get("default_account"):
            return

        self.config["default_account"] = account
        save_config(self.config)


class RepositoryCommand(BaseCommand):
    """A command that operates on a directory of recipe files."""

    _repository: Repository | None = None

    @classmethod
    def _add_arguments(
        cls, parser: argparse.ArgumentParser, config: ConfigDict
    ) -> None:
        parser.add_argument(
            "--directory",
            type=Path,
            default=None,
            help=(
                "the recipe directory to work in; by default, the current "
                "directory or the nearest parent of it that is one."
            ),
        )
        super()._add_arguments(parser, config)

    @property
    def repository(self) -> Repository:
        if self._repository is None:
            self._repository = Repository.find(self.options.directory)

        return self._repository


class RepositorySyncCommand(RepositoryCommand, RemoteCommand):
    """A command that syncs a directory of recipe files against an account.

    The directory remembers which account it was cloned from, so that syncing
    it does the same thing wherever it is run from and whatever the machine's
    default account happens to be.  An explicit `--account` still wins, which
    is what makes it possible to copy a directory into another account.
    """

    def default_account(self) -> str:
        return self.repository.config.account or super().default_account()

    def get_domain(self) -> str:
        return self.options.domain or self.repository.config.domain
