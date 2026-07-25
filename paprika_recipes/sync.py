"""Reconciling a working directory against a Paprika account.

Syncing here means what it means in git: each side may have moved since we last
looked, and our job is to work out which, apply whatever can be applied safely,
and say plainly what could not.

Three questions decide every recipe, and they are asked in this order:

1.  *Has the server's copy moved?*  The sync index gives us a `(uid, hash)`
    pair for every recipe in a single request, and the base copy remembers the
    hash the recipe carried when we pulled it.  If they agree, the server's
    copy is where we left it.  (This is the only thing Paprika's hash is good
    for -- it folds in the photo, so we cannot compute it ourselves.)
2.  *Has the local copy moved?*  `WorkingRecipe.has_local_changes` answers
    this by diffing the file against the base copy, ignoring edits that change
    only how the file is written rather than what it says.
3.  *Did both move?*  Then we do nothing and report a conflict.

That last case could in principle be a three-way merge -- the base copy is
exactly the merge base one would need -- but a recipe is a handful of prose
blobs, and a merge that silently interleaved two versions of someone's
directions would be worse than being told to sort it out yourself.  So we
refuse and explain, and leave the fix to the person who knows which version
they meant.

Deletion is deliberately asymmetric.  A recipe that vanishes from the server is
removed from the working directory, but a file you delete locally is never
propagated: destroying a recipe in someone's Paprika account is not something
to infer from an absent file.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .remote import RemoteRecipe
from .repository import Repository, Status, WorkingRecipe


class RemoteAccount(Protocol):
    """The part of `Remote` that syncing needs; a seam for testing."""

    def get_recipe_index(self) -> dict[str, str]: ...

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe: ...

    def upload_recipe(self, recipe: RemoteRecipe) -> RemoteRecipe: ...

    def notify(self) -> None: ...


class Action(Enum):
    """What became of a single recipe during a sync."""

    #: Written to the working directory for the first time.
    ADDED = "added"
    #: Rewritten in the working directory from a newer copy on the server.
    UPDATED = "updated"
    #: Removed from the working directory; it is no longer on the server.
    REMOVED = "removed"
    #: Uploaded to the server as a recipe it did not have.
    CREATED = "created"
    #: Uploaded to the server, replacing the copy it had.
    UPLOADED = "uploaded"
    #: Changed on both sides; left alone for the user to resolve.
    CONFLICT = "conflict"
    #: Nothing to do, for a reason worth mentioning.
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Change:
    action: Action
    uid: str
    name: str
    detail: str = ""


@dataclass
class SyncReport:
    """What a sync did, and what it declined to do."""

    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0

    def record(self, action: Action, uid: str, name: str, detail: str = "") -> None:
        self.changes.append(Change(action, uid, name or uid, detail))

    def of(self, *actions: Action) -> list[Change]:
        """The changes matching any of `actions`, in the order they happened."""
        return [change for change in self.changes if change.action in actions]

    @property
    def conflicts(self) -> list[Change]:
        return self.of(Action.CONFLICT)

    def __bool__(self) -> bool:
        """Whether anything happened at all."""
        return bool(self.changes)


class Syncer:
    """Reconciles a `Repository` against a Paprika account."""

    def __init__(
        self,
        repository: Repository,
        remote: RemoteAccount,
        on_recipe: Callable[[str], None] | None = None,
    ):
        self._repository = repository
        self._remote = remote
        self._on_recipe = on_recipe

    # -- Pulling ------------------------------------------------------------

    def pull(self, dry_run: bool = False) -> SyncReport:
        """Bring the working directory up to date with the server."""
        report = SyncReport()

        index = self._remote.get_recipe_index()
        entries = {entry.uid: entry for entry in self._repository.status()}
        paths = {
            uid: entry.path for uid, entry in entries.items() if entry.path is not None
        }

        # Recipes the server still knows about but has moved to the trash; as
        # far as a recipe directory is concerned those are gone.
        trashed: set[str] = set()

        for uid in sorted(index):
            entry = entries.get(uid)

            if entry is not None and entry.base is not None:
                if entry.base.hash == index[uid]:
                    # The server's copy has not moved since we pulled it, so
                    # there is nothing to bring down -- whatever the user has
                    # done to the file locally is their business until they
                    # push it.
                    report.unchanged += 1
                    continue

            recipe = self._fetch(uid, index[uid])

            if recipe.in_trash:
                trashed.add(uid)
                continue

            if entry is None:
                if not dry_run:
                    paths[uid] = self._repository.store(recipe, paths)
                report.record(Action.ADDED, uid, recipe.name)
            elif entry.status is Status.ADDED:
                report.record(
                    Action.CONFLICT,
                    uid,
                    recipe.name,
                    "is on the server, but we have no record of having pulled it",
                )
            elif entry.status is Status.DELETED:
                report.record(
                    Action.CONFLICT,
                    uid,
                    recipe.name,
                    "was deleted locally, but has changed on the server",
                )
            elif entry.has_local_changes():
                report.record(
                    Action.CONFLICT,
                    uid,
                    recipe.name,
                    "has changed on the server and locally "
                    f"({', '.join(entry.changed_fields())})",
                )
            else:
                if not dry_run:
                    paths[uid] = self._repository.store(recipe, paths)
                report.record(Action.UPDATED, uid, recipe.name)

        self._pull_removals(report, set(index) - trashed, entries, dry_run)

        return report

    def _pull_removals(
        self,
        report: SyncReport,
        live_uids: set[str],
        entries: dict[str, WorkingRecipe],
        dry_run: bool,
    ) -> None:
        """Drop recipes the server no longer has."""
        for uid in sorted(self._repository.base_uids() - live_uids):
            entry = entries[uid]
            name = entry.base.name if entry.base is not None else uid

            if entry.status is not Status.DELETED and entry.has_local_changes():
                report.record(
                    Action.CONFLICT,
                    uid,
                    name,
                    "has changed locally, but is no longer on the server",
                )
                continue

            if not dry_run:
                if entry.path is not None:
                    entry.path.unlink(missing_ok=True)
                self._repository.delete_base(uid)

            report.record(Action.REMOVED, uid, name)

    # -- Pushing ------------------------------------------------------------

    def push(self, dry_run: bool = False) -> SyncReport:
        """Send local changes to the server."""
        report = SyncReport()

        index = self._remote.get_recipe_index()
        pushed: list[str] = []

        for entry in self._repository.status():
            if self._push_one(report, entry, index, dry_run):
                pushed.append(entry.uid)

        if pushed and not dry_run:
            # Ask Paprika to tell its apps that something changed, then take
            # the server's word for what each recipe now says.
            self._remote.notify()
            self._refresh(pushed)

        return report

    def _push_one(
        self,
        report: SyncReport,
        entry: WorkingRecipe,
        index: dict[str, str],
        dry_run: bool,
    ) -> bool:
        """Push a single recipe, reporting whether it was sent to the server."""
        if entry.status is Status.UNCHANGED:
            report.unchanged += 1
            return False

        if entry.status is Status.DELETED or entry.recipe is None:
            name = entry.base.name if entry.base is not None else entry.uid
            report.record(
                Action.SKIPPED,
                entry.uid,
                name,
                "was deleted locally; delete it in Paprika itself to remove it "
                "from the server",
            )
            return False

        name = entry.recipe.name

        if entry.status is Status.ADDED:
            if entry.uid in index:
                report.record(
                    Action.CONFLICT,
                    entry.uid,
                    name,
                    "is already on the server, but we have no record of having "
                    "pulled it; pull first to see what it says",
                )
                return False
        elif not entry.has_local_changes():
            report.record(
                Action.SKIPPED,
                entry.uid,
                name,
                "differs only in how the file is written, not in what it says",
            )
            return False
        elif entry.base is not None and index.get(entry.uid) != entry.base.hash:
            report.record(
                Action.CONFLICT,
                entry.uid,
                name,
                "has changed on the server since it was pulled; pull first",
            )
            return False

        action = Action.CREATED if entry.status is Status.ADDED else Action.UPLOADED

        if not dry_run:
            self._notify(name)
            self._remote.upload_recipe(entry.recipe)

        report.record(action, entry.uid, name)

        return not dry_run

    def _refresh(self, uids: Iterable[str]) -> None:
        """Re-pull recipes we just uploaded, so their base copies are the server's.

        Uploading rewrites a recipe's hash, and Paprika may normalise other
        parts of it besides; asking for the recipe back is the only way to know
        what the server now believes, and it leaves the working file matching
        its base copy rather than looking eternally modified.
        """
        index = self._remote.get_recipe_index()
        paths = self._repository.paths_by_uid()

        for uid in uids:
            if uid not in index:
                continue

            self._repository.store(self._fetch(uid, index[uid]), paths)

    # -- Plumbing -----------------------------------------------------------

    def _fetch(self, uid: str, hash: str) -> RemoteRecipe:
        recipe = self._remote.get_recipe_by_id(uid, hash)
        self._notify(recipe.name)

        return recipe

    def _notify(self, name: str) -> None:
        if self._on_recipe is not None:
            self._on_recipe(name)
