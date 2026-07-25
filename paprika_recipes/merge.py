"""Reconciling a recipe that changed both locally and on the server.

The base copy is a complete record of what the recipe said when we last
pulled it, which is exactly the third input a three-way merge needs.  Where
both sides changed different parts of the directions, both changes survive;
only where they changed *the same* lines does anyone have to intervene.

Two kinds of field are treated quite differently, and the split is the whole
design:

Prose -- description, ingredients, directions, notes, nutritional info -- is
merged line by line, and genuinely overlapping edits are marked with the same
conflict markers git uses.  This works because the markers are themselves
text: they can sit in the file, be read back, and be edited away.

Everything else -- the name, the rating, the times, the categories -- has no
such escape hatch.  A rating cannot hold "either 4 or 5, you decide".  So if
one of those changed on both sides to different values, we do not merge the
recipe at all; we leave both copies exactly as they are and say so.  Taking
one side silently would throw away the other, and there would be nothing left
in the file to show that we had.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Final, TypeVar

from .markdown import BODY_FIELDS, TITLE_FIELD

if TYPE_CHECKING:
    from .recipe import BaseRecipe

T = TypeVar("T", bound="BaseRecipe")

#: A range of the base text that one side replaced, and what with.
_Change = tuple[int, int, list[str]]

#: Fields we can merge line by line.  The name is deliberately not among them:
#: it is a single line that becomes the document's title, and a conflict
#: marker in a title is worse than being asked to choose.
MERGEABLE_FIELDS: Final = frozenset(BODY_FIELDS - {TITLE_FIELD})

#: Never diffed on either side -- it is the server's token, not a value.
IGNORED_FIELDS: Final = frozenset({"hash"})

OURS: Final = "<<<<<<< yours"
SEPARATOR: Final = "======="
THEIRS: Final = ">>>>>>> paprika"

#: Matches an unresolved marker at the start of a line, which is the only
#: place one of ours can be.
CONFLICT_MARKER: Final = re.compile(r"^(<{7}|>{7})", re.MULTILINE)


@dataclass(frozen=True)
class Merge:
    """The result of reconciling one recipe."""

    #: The merged recipe, or None if it could not be merged at all.
    recipe: Any
    #: Prose fields that needed conflict markers.
    conflicted: tuple[str, ...] = ()
    #: Fields that changed on both sides and cannot hold both answers.
    unmergeable: tuple[str, ...] = ()

    @property
    def merged(self) -> bool:
        return self.recipe is not None

    @property
    def clean(self) -> bool:
        """Did everything reconcile without anyone needing to intervene?"""
        return self.merged and not self.conflicted


def merge_recipes(base: T, local: T, remote: T) -> Merge:
    """Reconcile a recipe that has changed on both sides since `base`."""
    changes: dict[str, Any] = {}
    conflicted: list[str] = []
    unmergeable: list[str] = []

    for name in sorted(base.as_dict()):
        if name in IGNORED_FIELDS:
            continue

        was = getattr(base, name)
        ours = getattr(local, name)
        theirs = getattr(remote, name)

        if ours == theirs:
            changes[name] = ours
            continue

        if ours == was:
            changes[name] = theirs
            continue

        if theirs == was:
            changes[name] = ours
            continue

        if name not in MERGEABLE_FIELDS:
            unmergeable.append(name)
            continue

        text, conflicts = merge_text(was or "", ours or "", theirs or "")
        changes[name] = text

        if conflicts:
            conflicted.append(name)

    if unmergeable:
        return Merge(None, tuple(conflicted), tuple(unmergeable))

    return Merge(replace(remote, **changes), tuple(conflicted), ())


def merge_text(base: str, local: str, remote: str) -> tuple[str, int]:
    """Merge three versions of a blob of text, line by line."""
    merged, conflicts = merge_lines(
        base.split("\n"), local.split("\n"), remote.split("\n")
    )

    return "\n".join(merged), conflicts


def merge_lines(
    base: list[str], local: list[str], remote: list[str]
) -> tuple[list[str], int]:
    """Merge two sets of edits to the same lines.

    Each side's edits are first expressed as the ranges of `base` it replaced.
    Ranges that do not overlap are independent, so both are applied; ranges
    that do overlap are grown into a single region and reconciled together.
    Only a region both sides changed *differently* is a conflict.

    Working in ranges rather than in lines-both-sides-kept is what lets two
    edits to adjacent lines both survive: there need not be an untouched line
    between them for them to be independent.
    """
    ours = _changes(base, local)
    theirs = _changes(base, remote)

    merged: list[str] = []
    conflicts = 0
    at = 0
    o = t = 0

    while o < len(ours) or t < len(theirs):
        start = min(
            ours[o][0] if o < len(ours) else len(base),
            theirs[t][0] if t < len(theirs) else len(base),
        )
        end = start
        mine: list[_Change] = []
        yours: list[_Change] = []

        # Everything beginning right here belongs to this region...
        while o < len(ours) and ours[o][0] == start:
            end = max(end, ours[o][1])
            mine.append(ours[o])
            o += 1

        while t < len(theirs) and theirs[t][0] == start:
            end = max(end, theirs[t][1])
            yours.append(theirs[t])
            t += 1

        # ...as does anything that turns out to overlap it once it has grown.
        expanded = True
        while expanded:
            expanded = False

            while o < len(ours) and ours[o][0] < end:
                end = max(end, ours[o][1])
                mine.append(ours[o])
                o += 1
                expanded = True

            while t < len(theirs) and theirs[t][0] < end:
                end = max(end, theirs[t][1])
                yours.append(theirs[t])
                t += 1
                expanded = True

        merged.extend(base[at:start])
        at = end

        if not yours:
            merged.extend(_apply(base, mine, start, end))
            continue

        if not mine:
            merged.extend(_apply(base, yours, start, end))
            continue

        ours_here = _apply(base, mine, start, end)
        theirs_here = _apply(base, yours, start, end)

        if ours_here == theirs_here:
            merged.extend(ours_here)
            continue

        merged.extend([OURS, *ours_here, SEPARATOR, *theirs_here, THEIRS])
        conflicts += 1

    merged.extend(base[at:])

    return merged, conflicts


def has_conflict_markers(recipe: BaseRecipe) -> bool:
    """Is someone still part-way through resolving a merge?"""
    return any(
        CONFLICT_MARKER.search(getattr(recipe, name, "") or "")
        for name in MERGEABLE_FIELDS
    )


def _changes(base: list[str], other: list[str]) -> list[_Change]:
    """Each range of `base` that `other` replaced, and what it replaced it with."""
    matcher = SequenceMatcher(None, base, other, autojunk=False)

    return [
        (start, end, other[from_:to])
        for tag, start, end, from_, to in matcher.get_opcodes()
        if tag != "equal"
    ]


def _apply(base: list[str], changes: list[_Change], start: int, end: int) -> list[str]:
    """What `base[start:end]` looks like once `changes` are applied to it."""
    result: list[str] = []
    at = start

    for change_start, change_end, lines in changes:
        result.extend(base[at:change_start])
        result.extend(lines)
        at = change_end

    result.extend(base[at:end])

    return result
