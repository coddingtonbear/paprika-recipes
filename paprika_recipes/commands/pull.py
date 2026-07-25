import argparse

from rich.console import Console

from ..command import RepositorySyncCommand
from ..reporting import print_report, recipe_progress
from ..sync import Syncer
from ..types import ConfigDict


class Command(RepositorySyncCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Brings a directory of recipe files up to date with paprika."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report what would change without changing anything.",
        )

    def handle(self) -> None:
        console = Console()
        remote = self.get_remote()

        with recipe_progress(console, "Pulling") as on_recipe:
            report = Syncer(self.repository, remote, on_recipe).pull(
                dry_run=self.options.dry_run
            )

        print_report(console, report, dry_run=self.options.dry_run)
