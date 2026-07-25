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
3.  *Did both move?*  Then we merge.  The base copy is exactly the third
    input a three-way merge needs, so edits to different parts of a recipe
    both survive and only genuinely overlapping ones need anyone's attention.
    See `merge` for what can and cannot be reconciled that way.

A merged file is left holding the merge while its base copy holds the
server's copy, which is what makes the result a local change like any other:
`status` shows it, `push` sends it, `restore` throws it away.  A merge that
needed conflict markers is not pushable until the markers are gone -- `push`
refuses it -- so a half-resolved merge cannot reach the server.

Deletion travels in both directions, but never destructively.  A recipe that
vanishes from the server is removed from the working directory; a file deleted
locally is pushed as a move into Paprika's trash.  Paprika's sync API has no
delete verb at all -- only an `in_trash` flag -- which happens to be exactly
the semantics worth wanting: the recipe is recoverable from the app's own
trash, and locally it can be brought back with `restore`, since the base copy
is a complete recipe and is not discarded until the trashing succeeds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Protocol

from .exceptions import PaprikaError, PaprikaUserError
from .markdown import PHOTO_FIELDS, foreign_uid_key
from .merge import has_conflict_markers, merge_recipes
from .remote import RemoteRecipe
from .repository import (
    CONFIG_FILENAME,
    REPOSITORY_DIRNAME,
    Repository,
    Status,
    WorkingRecipe,
)


class RemoteAccount(Protocol):
    """The part of `Remote` that syncing needs; a seam for testing."""

    def get_recipe_index(self) -> dict[str, str]: ...

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe: ...

    def download_photo(self, url: str) -> bytes: ...

    def upload_recipe(self, recipe: RemoteRecipe) -> RemoteRecipe: ...

    def notify(self) -> None: ...


class Action(Enum):
    """What became of a single recipe during a sync."""

    #: Written to the working directory for the first time.
    ADDED = "added"
    #: Rewritten in the working directory from a newer copy on the server.
    UPDATED = "updated"
    #: Changed on both sides and reconciled without anyone having to help.
    MERGED = "merged"
    #: Removed from the working directory; it is no longer on the server.
    REMOVED = "removed"
    #: Uploaded to the server as a recipe it did not have.
    CREATED = "created"
    #: Uploaded to the server, replacing the copy it had.
    UPLOADED = "uploaded"
    #: Moved into Paprika's trash, because its file was deleted locally.
    TRASHED = "trashed"
    #: Put back the way it last arrived from the server.
    RESTORED = "restored"
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


def refuse_unidentifiable(entries: list[WorkingRecipe]) -> None:
    """Stop a push that has clearly misread the directory rather than acting on it.

    Every recipe file carries the uid of the recipe it is.  If we stop being
    able to read those -- a `frontmatter_prefix` that no longer matches what
    the files were written with, a vault plugin that prunes frontmatter keys
    it does not recognise -- then the directory looks, from in here, exactly
    like someone having deleted every recipe they had and written the same
    number of new ones.  Acting on that reading would trash the whole account
    and upload a duplicate of everything in it.

    Two signals distinguish that from the real thing, because in the real
    thing the *files* are gone:

    The precise one is a file with no uid that nonetheless carries something
    called a uid.  A recipe somebody wrote themselves has no such key; a
    recipe we wrote and can no longer read does.

    The blunt one is for a directory whose uids were removed outright, which
    leaves no evidence to find: every recipe we have ever pulled is missing
    its file, and there are unidentified files sitting there instead.  One
    recipe deleted and one written is an ordinary afternoon, so this needs at
    least two, and even then it is only ever raised in preference to deleting
    somebody's entire collection.
    """
    untracked = [entry for entry in entries if entry.untracked]

    if not untracked:
        return

    for entry in untracked:
        key = foreign_uid_key(entry.extras)

        if key:
            raise PaprikaUserError(
                f"{entry.path} has a `{key}:` in its frontmatter, but no uid "
                "this directory can read. That usually means the file was "
                "written with a different `frontmatter_prefix` than the one "
                f"in {REPOSITORY_DIRNAME}/{CONFIG_FILENAME}. Nothing has been "
                "pushed; a push would upload this as a new recipe and trash "
                "the one it already is."
            )

    tracked = [entry for entry in entries if not entry.untracked]
    missing = [entry for entry in tracked if entry.status is Status.DELETED]

    if len(missing) > 1 and len(missing) == len(tracked):
        raise PaprikaUserError(
            f"Every one of the {len(missing)} recipes this directory has "
            f"pulled is missing its file, and {len(untracked)} "
            f"{'file' if len(untracked) == 1 else 'files'} we cannot identify "
            "are here instead. That is what a directory looks like when its "
            "recipe files have stopped being readable, so nothing has been "
            "pushed.\n\nIf you really did mean to delete every recipe, move "
            "the unidentified files out of the directory, push, and move them "
            "back."
        )


def restore(repository: Repository, entries: Iterable[WorkingRecipe]) -> SyncReport:
    """Put the given recipes back the way they last arrived from the server.

    This needs no network at all: the base copies are the only thing being
    read.  It is the undo for anything `status` reports -- an edit, or the
    deletion of a file -- but pointedly not for a recipe that was never
    pulled, since there is nothing to put such a file back to and deleting
    someone's new work is not an undo.
    """
    report = SyncReport()

    for entry in entries:
        if entry.status is Status.UNCHANGED:
            report.unchanged += 1
            continue

        if entry.base is None:
            report.record(
                Action.SKIPPED,
                entry.uid,
                entry.name,
                "was never pulled from Paprika, so there is nothing to "
                "restore it to; delete the file yourself if you meant to",
            )
            continue

        repository.restore(entry.uid)
        report.record(Action.RESTORED, entry.uid, entry.name)

    return report


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
                    # push it.  A photo whose attachment has gone missing is
                    # ours to put back, though; see `_ensure_photo`.
                    report.unchanged += 1

                    if not dry_run:
                        self._ensure_photo(report, entry.base)
                    continue

            recipe = self._fetch(uid, index[uid])

            if recipe.in_trash:
                trashed.add(uid)
                continue

            if entry is None:
                if not dry_run:
                    paths[uid] = self._repository.store(recipe, paths)
                    self._ensure_photo(report, recipe)
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
                    "was deleted locally, but has changed on the server; "
                    "push to trash it anyway, or `restore` to keep it",
                )
            elif entry.has_local_changes():
                paths[uid] = self._pull_merge(report, entry, recipe, paths, dry_run)
            else:
                if not dry_run:
                    paths[uid] = self._repository.store(recipe, paths)
                    self._ensure_photo(report, recipe)
                report.record(Action.UPDATED, uid, recipe.name)

        self._pull_removals(report, set(index) - trashed, entries, dry_run)

        return report

    def _pull_merge(
        self,
        report: SyncReport,
        entry: WorkingRecipe,
        remote: RemoteRecipe,
        paths: dict[str, Path],
        dry_run: bool,
    ) -> Path:
        """Reconcile a recipe that has moved on both sides."""
        # Guaranteed by the caller: this path is only reached for a recipe
        # that is present, tracked and locally changed.
        assert entry.base is not None
        assert entry.recipe is not None
        assert entry.path is not None

        merge = merge_recipes(entry.base, entry.recipe, remote)

        if not merge.merged:
            report.record(
                Action.CONFLICT,
                entry.uid,
                remote.name,
                f"changed on the server and locally, and {_and(merge.unmergeable)} "
                "cannot hold both answers; nothing was changed",
            )
            return entry.path

        if not dry_run:
            # The file holds the merge; the base copy holds what the server
            # holds, so that the merge is a local change we can then push.
            paths[entry.uid] = self._repository.store(merge.recipe, paths, base=remote)
            self._ensure_photo(report, remote)

        if merge.clean:
            report.record(
                Action.MERGED,
                entry.uid,
                remote.name,
                "changed on both sides; your edits were kept",
            )
        else:
            report.record(
                Action.CONFLICT,
                entry.uid,
                remote.name,
                f"{_and(merge.conflicted)} changed on both sides; resolve the "
                "conflict markers left in the file, then push",
            )

        return paths[entry.uid]

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
                self._repository.drop_photo(uid)

            report.record(Action.REMOVED, uid, name)

    # -- Pushing ------------------------------------------------------------

    def push(self, dry_run: bool = False) -> SyncReport:
        """Send local changes to the server."""
        report = SyncReport()

        entries = self._repository.status()
        refuse_unidentifiable(entries)

        index = self._remote.get_recipe_index()
        uploaded: list[str] = []

        for entry in entries:
            uid = self._push_one(report, entry, index, dry_run)

            if uid:
                uploaded.append(uid)

        if dry_run:
            return report

        if report.of(Action.CREATED, Action.UPLOADED, Action.TRASHED):
            # Ask Paprika to tell its apps that something changed.
            self._remote.notify()

        if uploaded:
            # Then take the server's word for what each recipe now says.
            self._refresh(report, uploaded)

        return report

    def _push_one(
        self,
        report: SyncReport,
        entry: WorkingRecipe,
        index: dict[str, str],
        dry_run: bool,
    ) -> str:
        """Push a single recipe; return its uid if it was sent to the server."""
        if entry.status is Status.UNCHANGED:
            report.unchanged += 1
            return ""

        if entry.status is Status.DELETED or entry.recipe is None:
            return self._push_removal(report, entry, index, dry_run)

        recipe = entry.recipe
        name = recipe.name

        if has_conflict_markers(recipe):
            report.record(
                Action.CONFLICT,
                entry.uid,
                name,
                "still has unresolved conflict markers in it; edit them out "
                "(or `restore` it) before pushing",
            )
            return ""

        if entry.status is Status.ADDED:
            if entry.untracked:
                if dry_run:
                    report.record(Action.CREATED, "", name)
                    return ""

                # Now that this recipe is about to exist on the server, it
                # needs an identity that outlives this run.
                entry = self._repository.adopt(entry)

                # Adopting only ever rewrites the uid of the recipe we just
                # read out of the file.
                assert entry.recipe is not None
                recipe = entry.recipe
            elif entry.uid in index:
                report.record(
                    Action.CONFLICT,
                    entry.uid,
                    name,
                    "is already on the server, but we have no record of having "
                    "pulled it; pull first to see what it says",
                )
                return ""
        elif not entry.has_local_changes():
            report.record(
                Action.SKIPPED,
                entry.uid,
                name,
                "differs only in how the file is written, not in what it says",
            )
            return ""
        elif entry.base is not None and index.get(entry.uid) != entry.base.hash:
            report.record(
                Action.CONFLICT,
                entry.uid,
                name,
                "has changed on the server since it was pulled; pull first",
            )
            return ""

        action = Action.CREATED if entry.status is Status.ADDED else Action.UPLOADED

        # What goes up is the file's recipe with the server's own photo put
        # back; see `_keep_servers_photo`.
        upload = _keep_servers_photo(recipe, entry.base)

        if not dry_run:
            self._notify(name)
            self._remote.upload_recipe(upload)

        # Uploading is the moment to say what is not being uploaded: the rest
        # of the file stays behind, and someone who wrote it there deserves to
        # be told rather than left to discover it.
        notes = []
        kept = entry.extras.describe()

        if kept:
            notes.append(f"{kept} stayed in your file")
        if upload.photo != recipe.photo:
            notes.append(
                "its photo stayed as the server has it; adding or removing "
                "photos from here is not supported yet"
            )

        report.record(action, entry.uid, name, "; ".join(notes))

        return "" if dry_run else entry.uid

    def _push_removal(
        self,
        report: SyncReport,
        entry: WorkingRecipe,
        index: dict[str, str],
        dry_run: bool,
    ) -> str:
        """Move a recipe whose file was deleted into Paprika's trash.

        The base copy is kept until the trashing has actually happened, so
        that a failure here leaves the recipe restorable rather than merely
        gone from both places.
        """
        name = entry.name

        if entry.base is None or entry.uid not in index:
            if not dry_run:
                self._repository.delete_base(entry.uid)
                self._repository.drop_photo(entry.uid)

            report.record(
                Action.REMOVED, entry.uid, name, "was already gone from the server"
            )
            return ""

        if index[entry.uid] != entry.base.hash:
            report.record(
                Action.CONFLICT,
                entry.uid,
                name,
                "was deleted locally, but has since changed on the server; "
                "pull to see what changed, or `restore` to keep it",
            )
            return ""

        if not dry_run:
            self._notify(name)
            self._remote.upload_recipe(replace(entry.base, in_trash=True))
            self._repository.delete_base(entry.uid)
            self._repository.drop_photo(entry.uid)

        report.record(Action.TRASHED, entry.uid, name)

        # Nothing to re-fetch: refreshing would write the file back out.
        return ""

    def _refresh(self, report: SyncReport, uids: Iterable[str]) -> None:
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

            recipe = self._fetch(uid, index[uid])
            self._repository.store(recipe, paths)
            self._ensure_photo(report, recipe)

    # -- Photos ---------------------------------------------------------------

    def _ensure_photo(self, report: SyncReport, recipe: RemoteRecipe) -> None:
        """Bring a recipe's photo down into `attachments/`, if it is not there.

        Called with what the recipe's *base copy* holds, since that is the
        photo its file's embed points at.  Doing nothing is the common case:
        the state file says we already downloaded this exact photo, and the
        attachment is still on disk.  Everything else -- a recipe seen for the
        first time, a photo replaced in the app, an attachment tidied away by
        hand -- ends the same way, with the photo downloaded again.

        A failure is reported rather than raised.  One unreachable image
        should not stop a pull, and because the attachment is simply left
        missing, every later pull keeps trying until it succeeds.
        """
        repository = self._repository

        try:
            if not recipe.photo:
                # The server's copy has no photo, so nothing should be left
                # sitting in `attachments/` claiming otherwise.
                repository.drop_photo(recipe.uid)
                return

            state = repository.read_photo_state(recipe.uid)

            if (
                state is not None
                and state.photo == recipe.photo
                and state.photo_hash == recipe.photo_hash
                and repository.attachment_path(recipe.photo).is_file()
            ):
                return

            if not recipe.photo_url:
                raise PaprikaError("the server did not say where to fetch it from")

            repository.write_photo(
                recipe.uid,
                recipe.photo,
                recipe.photo_hash,
                self._remote.download_photo(recipe.photo_url),
            )
        except (PaprikaError, PaprikaUserError) as e:
            report.record(
                Action.SKIPPED,
                recipe.uid,
                recipe.name,
                f"its photo could not be downloaded: {e}",
            )

    # -- Plumbing -----------------------------------------------------------

    def _fetch(self, uid: str, hash: str) -> RemoteRecipe:
        recipe = self._remote.get_recipe_by_id(uid, hash)
        self._notify(recipe.name)

        return recipe

    def _notify(self, name: str) -> None:
        if self._on_recipe is not None:
            self._on_recipe(name)


def _keep_servers_photo(
    recipe: RemoteRecipe, base: RemoteRecipe | None
) -> RemoteRecipe:
    """The recipe as uploaded: the file's fields, but the server's photo.

    A photo cannot yet be added or removed by editing a file, and the file is
    parsed into the very recipe we upload -- so without this, deleting the
    embed line in passing would quietly clear the photo on the server, and an
    embed in a hand-written recipe would name a photo whose bytes were never
    uploaded.
    """
    source = base if base is not None else RemoteRecipe(uid=recipe.uid)

    return replace(recipe, **{name: getattr(source, name) for name in PHOTO_FIELDS})


def _and(names: Iterable[str]) -> str:
    """Join names the way a person would say them aloud."""
    names = list(names)

    if len(names) < 2:
        return "".join(names)

    return f"{', '.join(names[:-1])} and {names[-1]}"
