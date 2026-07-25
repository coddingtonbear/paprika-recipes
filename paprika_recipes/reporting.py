"""Showing the user what a sync did, or what their directory looks like."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Final

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from .repository import Status, WorkingRecipe
from .sync import Action, SyncReport

#: Colour says what *kind* of thing happened, consistently across every
#: listing: green for something appearing, red for something going away,
#: yellow for something changing in place. Conflicts get magenta rather than
#: yellow -- they are the one outcome that needs the reader to do something,
#: so they should not blend in with the ordinary business of a recipe having
#: changed.
#:
#: These are the terminal's own palette colours, and deliberately nothing
#: else: they are themed by whoever is reading, so they are legible against
#: their background by construction.  An absolute colour -- `bright_black`,
#: `white`, a hex value -- is a guess about a background we cannot see, and
#: `bright_black` in particular is invisible on a dark terminal.
GONE: Final = "red"
NEW: Final = "green"
CHANGED: Final = "yellow"
NEEDS_ATTENTION: Final = "magenta"

#: De-emphasis is an *attribute* rather than a colour for the same reason: it
#: dims the reader's own foreground colour instead of replacing it.  Where a
#: terminal does not support it the text simply renders normally, which is the
#: right way for this to fail -- legible, just not quiet.
QUIET: Final = "dim"

#: How each outcome is labelled and coloured.  The labels are padded to a
#: common width so that a report reads as a column rather than a ragged list.
ACTION_STYLES: Final[dict[Action, tuple[str, str]]] = {
    Action.ADDED: ("added", NEW),
    Action.MERGED: ("merged", CHANGED),
    Action.CREATED: ("created", NEW),
    Action.RESTORED: ("restored", NEW),
    Action.UPDATED: ("updated", CHANGED),
    Action.UPLOADED: ("uploaded", CHANGED),
    Action.REMOVED: ("removed", GONE),
    Action.TRASHED: ("trashed", GONE),
    Action.CONFLICT: ("conflict", NEEDS_ATTENTION),
    Action.SKIPPED: ("skipped", QUIET),
}

#: Borrowed from `git status` verbatim, because a person who has used git
#: already knows what these three words mean and does not need us to invent
#: synonyms for them.
STATUS_STYLES: Final[dict[Status, tuple[str, str]]] = {
    Status.ADDED: ("new file:", NEW),
    Status.MODIFIED: ("modified:", CHANGED),
    Status.DELETED: ("deleted:", GONE),
    Status.UNCHANGED: ("unchanged:", QUIET),
}

#: What `push` would do with a recipe in each state, said plainly.  A status
#: listing that only names the state leaves the reader to guess at the
#: consequence, and the consequence of a deletion is worth being sure about.
PUSH_INTENT: Final[dict[Status, str]] = {
    Status.ADDED: "will be created in Paprika",
    Status.DELETED: "will be moved to Paprika's trash",
}

#: Shown in place of the ordinary label for a half-resolved merge, which is
#: the one state `push` will refuse outright.
CONFLICTED_LABEL: Final = ("conflicted:", NEEDS_ATTENTION)

ACTION_WIDTH: Final = max(len(label) for label, _ in ACTION_STYLES.values())
STATUS_WIDTH: Final = max(len(label) for label, _ in STATUS_STYLES.values())


#: Bumped when the shape below changes in a way that could break a reader.
#: Published output is an interface: a script that parses it is entitled to
#: know when it has stopped being the thing it was written against.
JSON_VERSION: Final = 1


def emit_json(payload: dict[str, Any]) -> None:
    """Write a command's result to stdout, and nothing else to stdout.

    Deliberately not `rich`: this is data rather than something being shown to
    anyone, and it should not be wrapped, highlighted or re-flowed to fit a
    terminal that may not even be there.
    """
    json.dump({"version": JSON_VERSION, **payload}, sys.stdout, indent=2)
    sys.stdout.write("\n")


def report_as_json(report: SyncReport, dry_run: bool = False) -> dict[str, Any]:
    """What a sync did, for a reader that is not a person.

    Built from the enum values and the uid rather than from the labels above,
    which exist to be reworded whenever a better wording turns up.
    """
    return {
        "dry_run": dry_run,
        "unchanged": report.unchanged,
        "changes": [
            {
                "action": change.action.value,
                "uid": change.uid or None,
                "name": change.name,
                "detail": change.detail,
            }
            for change in report.changes
        ],
    }


def status_as_json(entries: list[WorkingRecipe]) -> dict[str, Any]:
    """The state of a working directory, for a reader that is not a person."""
    interesting = [entry for entry in entries if entry.status is not Status.UNCHANGED]

    return {
        "unchanged": len(entries) - len(interesting),
        "recipes": [
            {
                # A recipe nobody has pushed yet genuinely has no uid; saying
                # so is more honest than inventing one for the occasion.
                "uid": entry.uid or None,
                "name": entry.name,
                "path": str(entry.path) if entry.path is not None else None,
                "status": entry.status.value,
                "conflicted": entry.conflicted,
                "changed_fields": entry.changed_fields(),
                "unsyncable": sorted(entry.extras.frontmatter)
                + [section.text.split("\n", 1)[0] for section in entry.extras.sections],
            }
            for entry in sorted(interesting, key=lambda entry: entry.name)
        ],
    }


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
    # Grouped by outcome rather than left in the order things happened, the
    # same way `git status` groups its listing: a report is read to find out
    # what became of everything, not to replay the sequence.
    order = list(ACTION_STYLES)

    for change in sorted(
        report.changes, key=lambda change: (order.index(change.action), change.name)
    ):
        label, color = ACTION_STYLES[change.action]
        detail = f" [{QUIET}]-- {change.detail}[/{QUIET}]" if change.detail else ""

        console.print(
            f"[{color}]{label:>{ACTION_WIDTH}}[/{color}]  {change.name}{detail}"
        )

    if not report.changes:
        console.print(
            f"[{QUIET}]Nothing to do; {report.unchanged} "
            f"{_recipes(report.unchanged)} already in sync.[/{QUIET}]"
        )
        return

    if dry_run:
        console.print(f"\n[{QUIET}]Nothing was changed (--dry-run).[/{QUIET}]")

    conflicts = report.conflicts
    if conflicts:
        console.print(
            f"\n[{NEEDS_ATTENTION}]{len(conflicts)} {_recipes(len(conflicts))} "
            f"could not be synced automatically; resolve them and try "
            f"again.[/{NEEDS_ATTENTION}]"
        )


def print_status(console: Console, entries: list[WorkingRecipe]) -> None:
    """Print the state of a working directory, in the shape of `git status`."""
    interesting = [entry for entry in entries if entry.status is not Status.UNCHANGED]
    unchanged = len(entries) - len(interesting)

    if not interesting:
        console.print(
            f"[{QUIET}]Nothing to sync; all {unchanged} "
            f"{_recipes(unchanged)} match the last pull.[/{QUIET}]"
        )
        return

    console.print("Changes not yet sent to Paprika:")
    console.print(f'[{QUIET}]  (use "paprika-recipes push" to send them)[/{QUIET}]')
    console.print(
        f'[{QUIET}]  (use "paprika-recipes restore <recipe>..." to discard '
        f"them)[/{QUIET}]"
    )
    console.print()

    for entry in sorted(interesting, key=lambda entry: entry.name):
        if entry.conflicted:
            label, color = CONFLICTED_LABEL
        else:
            label, color = STATUS_STYLES[entry.status]

        detail = _status_detail(entry)

        console.print(
            f"        [{color}]{label:<{STATUS_WIDTH}} {entry.name}[/{color}]"
            + (f" [{QUIET}]({detail})[/{QUIET}]" if detail else "")
        )

    if unchanged:
        console.print(
            f"\n[{QUIET}]{unchanged} other {_recipes(unchanged)} "
            f"match the last pull.[/{QUIET}]"
        )

    print_unsyncable(console, entries)


def print_unsyncable(console: Console, entries: list[WorkingRecipe]) -> None:
    """Say how much of the directory Paprika has nowhere to put.

    Only a count, and only once: a vault where every recipe carries a `tags:`
    would otherwise produce a wall of text on every run.  What each individual
    file is holding is said at the moment it matters -- beside the recipe in a
    listing that already names it, and again as it is pushed.
    """
    holding = [entry for entry in entries if entry.extras]

    if not holding:
        return

    console.print(
        f"\n[{QUIET}]{len(holding)} {_recipes(len(holding))} "
        f"{'contains' if len(holding) == 1 else 'contain'} content of your own "
        f"that Paprika cannot store; it stays in your files and is never "
        f"uploaded.[/{QUIET}]"
    )


def _status_detail(entry: WorkingRecipe) -> str:
    if entry.conflicted:
        return "unresolved conflict markers; edit them out, then push"

    if entry.status is Status.MODIFIED:
        fields = entry.changed_fields()
        detail = ", ".join(fields) if fields else "formatting only; nothing to push"
    else:
        detail = PUSH_INTENT.get(entry.status, "")

    if entry.extras:
        kept = f"keeping {entry.extras.describe()}"
        detail = f"{detail}; {kept}" if detail else kept

    return detail


def _recipes(count: int) -> str:
    return "recipe" if count == 1 else "recipes"
