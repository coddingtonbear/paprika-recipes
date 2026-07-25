import argparse
from pathlib import Path

from rich.console import Console

from ..command import RepositoryCommand
from ..exceptions import PaprikaUserError
from ..reporting import print_report
from ..repository import Status, WorkingRecipe
from ..sync import restore
from ..types import ConfigDict


def matches(entry: WorkingRecipe, target: str) -> bool:
    """Does `target` name this recipe?

    A recipe can be named by its title, its uid, or the path of its file --
    and a deleted recipe has no file left to name, which is exactly when
    restoring matters most, so the title has to work on its own.
    """
    if target == entry.uid or target.casefold() == entry.name.casefold():
        return True

    if entry.path is None:
        return False

    return Path(target).resolve() == entry.path.resolve()


class Command(RepositoryCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Undoes local changes to recipes, including deleting them."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument(
            "recipes",
            nargs="*",
            type=str,
            help="the recipes to restore, by title, filename, or uid.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="restore every recipe that has been changed or deleted.",
        )

    def handle(self) -> None:
        console = Console()

        entries = self.repository.status()
        changed = [entry for entry in entries if entry.status is not Status.UNCHANGED]

        if self.options.all:
            selected = changed
        else:
            selected = self.select(changed)

        if not selected:
            console.print(
                "[bright_black]Nothing to restore; no recipes have been "
                "changed.[/bright_black]"
            )
            return

        print_report(console, restore(self.repository, selected))

    def select(self, changed: list[WorkingRecipe]) -> list[WorkingRecipe]:
        """Pick out the recipes named on the command line."""
        if not self.options.recipes:
            if not changed:
                return []

            raise PaprikaUserError(
                "Name the recipes you would like to restore, or pass --all to "
                "restore every one of these:\n"
                + "\n".join(f"  {entry.name}" for entry in changed)
            )

        selected: list[WorkingRecipe] = []

        for target in self.options.recipes:
            found = [entry for entry in changed if matches(entry, target)]

            if not found:
                raise PaprikaUserError(
                    f"No changed recipe matches {target!r}; run "
                    "`paprika-recipes status` to see what can be restored."
                )

            selected.extend(found)

        return selected
