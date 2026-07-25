import argparse
from pathlib import Path

from rich.console import Console

from ..command import RemoteCommand
from ..constants import ExitCode
from ..exceptions import PaprikaUserError
from ..reporting import print_report, recipe_progress
from ..repository import REPOSITORY_DIRNAME, Repository, RepositoryConfig
from ..sync import Syncer


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Creates a directory of recipe files from a paprika account."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        # Named first and required, the way git wants the thing being cloned
        # named first. Which account a directory of recipes belongs to is not
        # a detail to be inferred: it decides what is about to be written and
        # where everything in it will be sent from then on.
        parser.add_argument(
            "account",
            type=str,
            help="the e-mail address of the paprika account to clone.",
        )
        parser.add_argument(
            "directory",
            type=Path,
            nargs="?",
            default=Path.cwd(),
            help="where to put the recipes; default: the current directory.",
        )

    def handle(self) -> ExitCode:
        console = Console()
        directory: Path = self.options.directory

        if (directory / REPOSITORY_DIRNAME).is_dir():
            raise PaprikaUserError(
                f"{directory} is already a paprika recipe directory; "
                "run `paprika-recipes pull` to bring it up to date."
            )

        remote = self.get_remote()

        # Only once we know we can reach the account -- an empty directory
        # left behind by a failed login is just litter.
        repository = Repository.initialize(
            directory,
            RepositoryConfig(account=self.get_account(), domain=self.get_domain()),
        )

        with recipe_progress(console, "Cloning") as on_recipe:
            report = Syncer(repository, remote, on_recipe).pull()

        print_report(console, report)
        console.print(f"\nCloned into [bold]{repository.root}[/bold].")

        return ExitCode.ATTENTION if report.conflicts else ExitCode.SUCCESS
