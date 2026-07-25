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
from .utils import get_cache_dir

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
    _console: Console | None = None

    def __init__(self, options: argparse.Namespace):
        self._options: argparse.Namespace = options
        super().__init__()

    @property
    def options(self) -> argparse.Namespace:
        """Provides options provided at the command-line."""
        return self._options

    @property
    def json_output(self) -> bool:
        """Is this run being read by a program rather than a person?"""
        return bool(getattr(self.options, "json", False))

    @property
    def console(self) -> Console:
        """Where anything meant for a person goes.

        Under `--json` that is stderr, because stdout belongs entirely to the
        data -- a progress bar written across it would leave the output
        unparseable.  That console is also declared non-interactive, so that a
        missing password is an error rather than a prompt: a script waiting on
        a prompt it cannot see is indistinguishable from one that has hung.
        """
        if self._console is None:
            self._console = Console(
                stderr=self.json_output,
                force_interactive=False if self.json_output else None,
            )

        return self._console

    @classmethod
    def get_help(cls) -> str:
        """Retuurns help text for this function."""
        return ""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:  # noqa: B027
        """Allows adding additional command-line arguments."""

    @classmethod
    def _add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help=(
                "write what happened to stdout as JSON, and everything meant "
                "for a person to stderr."
            ),
        )
        cls.add_arguments(parser)

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
    def _add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Allows adding additional command-line arguments."""
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
        super()._add_arguments(parser)

    def get_account(self) -> str:
        """Which account to talk to.

        There is deliberately no fallback to a remembered default. An account
        is either named on the command line or recorded in the directory being
        synced, and both of those say plainly which recipes are about to be
        touched; a machine-wide default does not, and quietly decides for you
        which of your accounts a `clone` belongs to.
        """
        return self._account or getattr(self.options, "account", "") or ""

    def get_domain(self) -> str:
        return self.options.domain or DEFAULT_DOMAIN

    def get_remote(self) -> Remote:
        """Connect to an account, asking for whatever we have not been told."""
        console = self.console

        self._account = self.get_account() or ask_for_account(console)

        return authenticate(self._account, self.get_domain(), self.get_cache(), console)


class RepositoryCommand(BaseCommand):
    """A command that operates on a directory of recipe files."""

    _repository: Repository | None = None

    @classmethod
    def _add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--directory",
            type=Path,
            default=None,
            help=(
                "the recipe directory to work in; by default, the current "
                "directory or the nearest parent of it that is one."
            ),
        )
        super()._add_arguments(parser)

    @property
    def repository(self) -> Repository:
        if self._repository is None:
            self._repository = Repository.find(self.options.directory)

        return self._repository


class RepositorySyncCommand(RepositoryCommand, RemoteCommand):
    """A command that syncs a directory of recipe files against an account.

    The directory remembers which account it was cloned from, so that syncing
    it does the same thing wherever it is run from.  That is the only place an
    account is ever remembered: there is nothing machine-wide to disagree with
    it.  An explicit `--account` still wins, which is what makes it possible to
    copy a directory into another account.
    """

    @classmethod
    def _add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--account",
            type=str,
            default="",
            help=(
                "the paprika account to talk to; defaults to the account this "
                "directory was cloned from. Naming a different one is how a "
                "directory is copied into another account."
            ),
        )
        super()._add_arguments(parser)

    def get_account(self) -> str:
        return super().get_account() or self.repository.config.account

    def get_domain(self) -> str:
        return self.options.domain or self.repository.config.domain
