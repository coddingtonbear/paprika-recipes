import argparse

from ..command import RepositorySyncCommand
from ..constants import ExitCode
from ..reporting import emit_json, print_report, recipe_progress, report_as_json
from ..sync import Syncer


class Command(RepositorySyncCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Brings a directory of recipe files up to date with paprika."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report what would change without changing anything.",
        )

    def handle(self) -> ExitCode:
        remote = self.get_remote()

        with recipe_progress(self.console, "Pulling") as on_recipe:
            report = Syncer(self.repository, remote, on_recipe).pull(
                dry_run=self.options.dry_run
            )

        if self.json_output:
            emit_json(report_as_json(report, dry_run=self.options.dry_run))
        else:
            print_report(self.console, report, dry_run=self.options.dry_run)

        return ExitCode.ATTENTION if report.conflicts else ExitCode.SUCCESS
