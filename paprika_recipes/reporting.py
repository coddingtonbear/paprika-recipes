"""Showing the user what a sync did, or what their directory looks like."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Final

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from .repository import Status, WorkingRecipe
from .sync import Action, SyncReport

#: How each outcome is labelled and coloured.  The labels are padded to a
#: common width so that a report reads as a column rather than a ragged list.
ACTION_STYLES: Final[dict[Action, tuple[str, str]]] = {
    Action.ADDED: ("added", "green"),
    Action.UPDATED: ("updated", "cyan"),
    Action.REMOVED: ("removed", "red"),
    Action.CREATED: ("created", "green"),
    Action.UPLOADED: ("uploaded", "cyan"),
    Action.CONFLICT: ("conflict", "yellow"),
    Action.SKIPPED: ("skipped", "bright_black"),
}

STATUS_STYLES: Final[dict[Status, tuple[str, str]]] = {
    Status.MODIFIED: ("modified", "cyan"),
    Status.ADDED: ("untracked", "green"),
    Status.DELETED: ("deleted", "red"),
    Status.UNCHANGED: ("unchanged", "bright_black"),
}

LABEL_WIDTH: Final = max(
    len(label) for label, _ in [*ACTION_STYLES.values(), *STATUS_STYLES.values()]
)


@contextmanager
def recipe_progress(
    console: Console, description: str
) -> Iterator[Callable[[str], None]]:
    """Show progress as recipes are fetched or sent.

    We do not know how many recipes a sync will need to touch until it is
    underway -- most of them usually turn out not to need touching at all --
    so this counts up rather than filling a bar.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(description, total=None)

        def on_recipe(name: str) -> None:
            progress.update(task, description=f"{description} {name}", advance=1)

        yield on_recipe


def print_report(console: Console, report: SyncReport, dry_run: bool = False) -> None:
    """Print what a sync did, followed by a one-line summary."""
    for change in report.changes:
        label, color = ACTION_STYLES[change.action]
        detail = (
            f" [bright_black]-- {change.detail}[/bright_black]" if change.detail else ""
        )

        console.print(
            f"[{color}]{label:>{LABEL_WIDTH}}[/{color}]  {change.name}{detail}"
        )

    if not report.changes:
        console.print(
            f"[bright_black]Nothing to do; {report.unchanged} "
            f"{_recipes(report.unchanged)} already in sync.[/bright_black]"
        )
        return

    if dry_run:
        console.print("\n[bright_black]Nothing was changed (--dry-run).[/bright_black]")

    conflicts = report.conflicts
    if conflicts:
        console.print(
            f"\n[yellow]{len(conflicts)} {_recipes(len(conflicts))} could not be "
            "synced automatically; resolve them and try again.[/yellow]"
        )


def print_status(console: Console, entries: list[WorkingRecipe]) -> None:
    """Print the state of a working directory, ignoring what is in sync."""
    interesting = [entry for entry in entries if entry.status is not Status.UNCHANGED]

    for entry in sorted(interesting, key=lambda entry: entry.name):
        label, color = STATUS_STYLES[entry.status]

        detail = ""
        if entry.status is Status.MODIFIED:
            fields = entry.changed_fields()
            detail = ", ".join(fields) if fields else "formatting only; nothing to push"

        detail = f" [bright_black]-- {detail}[/bright_black]" if detail else ""

        console.print(
            f"[{color}]{label:>{LABEL_WIDTH}}[/{color}]  {entry.name}{detail}"
        )

    unchanged = len(entries) - len(interesting)

    if not interesting:
        console.print(
            f"[bright_black]Nothing to sync; all {unchanged} "
            f"{_recipes(unchanged)} match the last pull.[/bright_black]"
        )
    elif unchanged:
        console.print(
            f"\n[bright_black]{unchanged} other {_recipes(unchanged)} "
            "match the last pull.[/bright_black]"
        )


def _recipes(count: int) -> str:
    return "recipe" if count == 1 else "recipes"
