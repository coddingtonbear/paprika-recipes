import argparse

from rich.console import Console

from ..command import RepositoryCommand
from ..constants import ExitCode
from ..reporting import print_status
from ..repository import Status


class Command(RepositoryCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Shows which recipe files have changed since the last sync."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--exit-code",
            action="store_true",
            help=(
                "exit non-zero if anything has changed, so that a script can "
                "test for it; after `git diff --exit-code`."
            ),
        )

    def handle(self) -> ExitCode:
        # Deliberately offline: this answers "what have I changed?", which is
        # a question about the directory alone. Whether the *server* has moved
        # is what `pull` is for.
        entries = self.repository.status()

        print_status(Console(), entries)

        # Having local changes is the ordinary state of a working directory,
        # so it is only an "attention" answer when someone asked the question.
        if self.options.exit_code and any(
            entry.status is not Status.UNCHANGED for entry in entries
        ):
            return ExitCode.ATTENTION

        return ExitCode.SUCCESS
