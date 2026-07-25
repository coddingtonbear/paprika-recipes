"""A working directory of recipe markdown files, plus the state needed to sync it.

The layout mirrors the one idea we are borrowing from git: alongside the files
you edit, we keep a pristine copy of every recipe exactly as it arrived from
the server.

    <root>/
        .paprika/
            config.yaml             -- which account this directory belongs to
            recipes/<uid>.json      -- the recipe as last pulled ("the base")
        <Recipe Name>.md            -- the file you actually edit

The base copies earn their keep twice over.  They are the merge base when both
sides of a sync have moved, and -- more importantly -- they are what makes
change detection reliable.

We decide whether a file has been edited by rendering its base copy and
comparing the resulting *text* against the file on disk, rather than by parsing
the file and comparing fields.  The distinction matters because it makes
correctness independent of how faithful our markdown round-trip is: both sides
of the comparison pass through the identical transformation, so any
normalisation the renderer performs cancels out.  Parsing only ever happens for
files we have already established were edited, which means an imperfect
round-trip can cost us accuracy in a field the user deliberately changed, but
can never silently rewrite the rest of the recipe or manufacture a spurious
upload.

Note also that we never recompute Paprika's `hash` to detect local edits.  For
any recipe with a photo the app folds the image into that value in a way we
cannot reproduce, so it is only meaningful as an opaque token for asking
whether the *server's* copy has moved.
"""

from __future__ import annotations

import json
from collections.abc import Container, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, TypeVar

from .constants import DEFAULT_DOMAIN
from .exceptions import PaprikaUserError
from .markdown import (
    Extras,
    documents_differ,
    find_lossy_fields,
    normalize_recipe,
    parse_document,
    parse_recipe,
    read_extras,
    render_recipe,
)
from .merge import has_conflict_markers
from .recipe import BaseRecipe
from .remote import RemoteRecipe
from .utils import dump_yaml, load_yaml

T = TypeVar("T", bound=BaseRecipe)

REPOSITORY_DIRNAME: Final = ".paprika"
BASE_DIRNAME: Final = "recipes"
CONFIG_FILENAME: Final = "config.yaml"
RECIPE_SUFFIX: Final = ".md"

#: Characters we refuse to put in a filename.  Paprika itself is happy with
#: any of them, but they are either illegal or a nuisance somewhere we might
#: reasonably expect a recipe directory to be synced to.
UNSAFE_FILENAME_CHARACTERS: Final = '/\\:*?"<>|'


class Status(Enum):
    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"


@dataclass(frozen=True)
class WorkingRecipe:
    """A recipe file in the working directory, and how it relates to its base."""

    uid: str
    status: Status
    path: Path | None
    recipe: RemoteRecipe | None
    base: RemoteRecipe | None
    #: What the file holds that Paprika has nowhere to put.
    extras: Extras = field(default_factory=Extras)

    @property
    def name(self) -> str:
        """What to call this recipe when talking to the user about it."""
        for recipe in (self.recipe, self.base):
            if recipe is not None and recipe.name:
                return recipe.name

        return self.uid

    def changed_fields(self) -> list[str]:
        """Which fields the user actually edited, relative to the base copy."""
        if self.recipe is None or self.base is None:
            return []

        current = self.recipe.as_dict()
        base = self.base.as_dict()

        return sorted(
            key
            for key in current
            # `hash` is the server's token, not ours to diff on.
            if key != "hash" and current[key] != base.get(key)
        )

    @property
    def conflicted(self) -> bool:
        """Is a merge still half-resolved in this file?"""
        return self.recipe is not None and has_conflict_markers(self.recipe)

    def has_local_changes(self) -> bool:
        """Is there anything here the server would care about?

        A file can be MODIFIED without this being true: the user may have
        reordered the frontmatter or reflowed a list, which changes the bytes
        on disk without changing the recipe.  Sync decisions key off this
        rather than off `status` alone, so that cosmetic edits neither
        manufacture an upload nor stand in the way of one.
        """
        if self.status in (Status.ADDED, Status.DELETED):
            return True

        return bool(self.changed_fields())


@dataclass
class RepositoryConfig:
    account: str = ""
    domain: str = DEFAULT_DOMAIN

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepositoryConfig:
        return cls(
            account=data.get("account", ""),
            domain=data.get("domain") or DEFAULT_DOMAIN,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"account": self.account, "domain": self.domain}


class Repository:
    _root: Path
    _config: RepositoryConfig | None

    def __init__(self, root: Path):
        self._root = root
        self._config = None

        if not self.repository_dir.is_dir():
            raise PaprikaUserError(
                f"{root} is not a paprika recipe directory; "
                "run `paprika-recipes clone` to create one."
            )

    # -- Locating and creating repositories ---------------------------------

    @classmethod
    def initialize(
        cls, root: Path, config: RepositoryConfig | None = None
    ) -> Repository:
        base_dir = root / REPOSITORY_DIRNAME / BASE_DIRNAME
        base_dir.mkdir(parents=True, exist_ok=True)

        repository = cls(root)
        repository.save_config(config if config is not None else RepositoryConfig())

        return repository

    @classmethod
    def find(cls, path: Path | None = None) -> Repository:
        """Find the repository containing `path`, searching upwards."""
        candidate = (path if path is not None else Path.cwd()).resolve()

        for directory in [candidate, *candidate.parents]:
            if (directory / REPOSITORY_DIRNAME).is_dir():
                return cls(directory)

        raise PaprikaUserError(
            f"No paprika recipe directory found in {candidate} or any parent "
            "directory; run `paprika-recipes clone` to create one."
        )

    # -- Layout -------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def repository_dir(self) -> Path:
        return self._root / REPOSITORY_DIRNAME

    @property
    def base_dir(self) -> Path:
        return self.repository_dir / BASE_DIRNAME

    @property
    def config_path(self) -> Path:
        return self.repository_dir / CONFIG_FILENAME

    # -- Configuration ------------------------------------------------------

    @property
    def config(self) -> RepositoryConfig:
        if self._config is None:
            if self.config_path.is_file():
                with open(self.config_path, encoding="utf-8") as inf:
                    self._config = RepositoryConfig.from_dict(load_yaml(inf) or {})
            else:
                self._config = RepositoryConfig()

        return self._config

    def save_config(self, config: RepositoryConfig) -> None:
        with open(self.config_path, "w", encoding="utf-8") as outf:
            dump_yaml(config.as_dict(), outf)

        self._config = config

    # -- The base (pristine) copies -----------------------------------------

    def base_path_for(self, uid: str) -> Path:
        return self.base_dir / f"{uid}.json"

    def read_base(self, uid: str) -> RemoteRecipe | None:
        path = self.base_path_for(uid)

        if not path.is_file():
            return None

        with open(path, encoding="utf-8") as inf:
            return RemoteRecipe.from_dict(json.load(inf))

    def write_base(self, recipe: RemoteRecipe) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

        with open(self.base_path_for(recipe.uid), "w", encoding="utf-8") as outf:
            json.dump(recipe.as_dict(), outf, indent=2, sort_keys=True)

    def delete_base(self, uid: str) -> None:
        self.base_path_for(uid).unlink(missing_ok=True)

    def base_uids(self) -> set[str]:
        if not self.base_dir.is_dir():
            return set()

        return {path.stem for path in self.base_dir.glob("*.json")}

    # -- The working directory ----------------------------------------------

    def working_paths(self) -> Iterator[Path]:
        yield from recipe_files(self._root)

    def read_working(self, path: Path) -> RemoteRecipe:
        return read_recipe(path, RemoteRecipe)

    def read_document(self, path: Path) -> tuple[RemoteRecipe, Extras]:
        """Read a working file as both a recipe and everything else it holds."""
        with open(path, encoding="utf-8") as inf:
            content = inf.read()

        try:
            return parse_document(content, RemoteRecipe)
        except PaprikaUserError as e:
            raise PaprikaUserError(f"{path}: {e}")

    def read_extras(self, path: Path) -> Extras:
        """The parts of a working file that are not the recipe; see `markdown`."""
        if not path.is_file():
            return Extras()

        with open(path, encoding="utf-8") as inf:
            return read_extras(inf.read(), RemoteRecipe)

    def write_working(
        self,
        recipe: RemoteRecipe,
        path: Path | None = None,
        extras: Extras | None = None,
    ) -> Path:
        lossy = find_lossy_fields(recipe, extras)
        if lossy:
            raise PaprikaUserError(
                f"Refusing to write {recipe.name!r}: {', '.join(lossy)} "
                "could not be read back from the markdown we would have "
                "written. Please report this as a bug."
            )

        if path is None:
            path = self.path_for(recipe)

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as outf:
            outf.write(render_recipe(recipe, extras))

        return path

    def store(
        self,
        recipe: RemoteRecipe,
        existing: dict[str, Path] | None = None,
        base: RemoteRecipe | None = None,
    ) -> Path:
        """Record a recipe as pulled: write the working file and its base copy.

        This is the only way the two should ever be written together, because
        it normalises once and uses the result for both. Writing them
        separately risks a base copy that does not render to the file beside
        it, which would make the recipe look permanently modified.

        `base` says what the *server* holds, for the one case where that is
        not what we are writing to the file: after a merge the file holds the
        merged result, while the base copy has to hold the server's copy.
        Otherwise the merge would look like it had already been pushed, and
        the optimistic-lock check would refuse to push it.
        """
        normalized = normalize_recipe(recipe)
        path = self.path_for(normalized, existing)

        self.write_working(normalized, path, self.read_extras(path))
        self.write_base(normalize_recipe(base) if base is not None else normalized)

        return path

    def restore(self, uid: str) -> Path:
        """Put a recipe's working file back the way it last arrived.

        This is the undo for local edits, including deleting the file: the
        base copy is a complete recipe, so there is always something to
        restore to as long as the recipe has been pulled at least once.
        """
        base = self.read_base(uid)

        if base is None:
            raise PaprikaUserError(
                f"There is no record of having pulled the recipe {uid}, "
                "so there is nothing to restore it to."
            )

        return self.store(base)

    def path_for(
        self, recipe: RemoteRecipe, existing: dict[str, Path] | None = None
    ) -> Path:
        """Choose a working file path for a recipe, avoiding collisions.

        Callers placing many recipes at once should pass `existing` (and keep
        it up to date themselves) to avoid re-reading the working directory
        for every single recipe.
        """
        if existing is None:
            existing = self.paths_by_uid()

        if recipe.uid in existing:
            return existing[recipe.uid]

        return unique_path(
            self._root, recipe, {path.resolve() for path in existing.values()}
        )

    def paths_by_uid(self) -> dict[str, Path]:
        """Map each recipe's uid to the file holding it.

        We read the uid out of each file rather than keeping an index, so that
        renaming a file in the working directory just works.
        """
        result: dict[str, Path] = {}

        for path in self.working_paths():
            recipe = self.read_working(path)

            if not recipe.uid:
                continue

            if recipe.uid in result:
                raise PaprikaUserError(
                    f"Two files claim the same recipe uid {recipe.uid}: "
                    f"{result[recipe.uid]} and {path}."
                )

            result[recipe.uid] = path

        return result

    # -- Change detection ---------------------------------------------------

    def is_modified(self, uid: str, path: Path) -> bool:
        """Has the working file diverged from the recipe we last pulled?

        Compares rendered text rather than parsed fields; see the module
        docstring for why that distinction is the load-bearing one.
        """
        base = self.read_base(uid)

        if base is None:
            return True

        with open(path, encoding="utf-8") as inf:
            content = inf.read()

        # Render the base with whatever of the file is the user's own, so
        # that their `tags:` or their own `## ` section is not mistaken for an
        # edit to the recipe.
        return documents_differ(
            content, render_recipe(base, read_extras(content, RemoteRecipe))
        )

    def status(self) -> list[WorkingRecipe]:
        paths = self.paths_by_uid()
        base_uids = self.base_uids()

        result: list[WorkingRecipe] = []

        for uid in sorted(set(paths) | base_uids):
            path = paths.get(uid)
            base = self.read_base(uid)

            if path is None:
                result.append(
                    WorkingRecipe(
                        uid=uid,
                        status=Status.DELETED,
                        path=None,
                        recipe=None,
                        base=base,
                    )
                )
                continue

            recipe, extras = self.read_document(path)

            if uid not in base_uids:
                status = Status.ADDED
            elif self.is_modified(uid, path):
                status = Status.MODIFIED
            else:
                status = Status.UNCHANGED

            result.append(
                WorkingRecipe(
                    uid=uid,
                    status=status,
                    path=path,
                    recipe=recipe,
                    base=base,
                    extras=extras,
                )
            )

        return result


def recipe_files(root: Path) -> Iterator[Path]:
    """Every recipe file under `root`, ignoring our own bookkeeping."""
    for path in sorted(root.rglob(f"*{RECIPE_SUFFIX}")):
        if REPOSITORY_DIRNAME in path.parts:
            continue

        yield path


def read_recipe(path: Path, recipe_class: type[T]) -> T:
    """Read a recipe from a file, blaming the file if it cannot be read."""
    with open(path, encoding="utf-8") as inf:
        content = inf.read()

    try:
        return parse_recipe(content, recipe_class)
    except PaprikaUserError as e:
        raise PaprikaUserError(f"{path}: {e}")


def unique_path(root: Path, recipe: BaseRecipe, taken: Container[Path]) -> Path:
    """Choose a file for a recipe, avoiding names already spoken for."""
    stem = safe_filename(recipe.name) or recipe.uid

    candidate = root / f"{stem}{RECIPE_SUFFIX}"
    if candidate.resolve() not in taken and not candidate.exists():
        return candidate

    # Two different recipes can share a name; fall back to disambiguating
    # with a slice of the uid, which is unique by construction.
    suffix = recipe.uid.split("-")[0]

    return root / f"{stem} ({suffix}){RECIPE_SUFFIX}"


def safe_filename(name: str) -> str:
    """Make a recipe's name safe to use as a filename."""
    cleaned = "".join(
        character
        for character in name
        if character not in UNSAFE_FILENAME_CHARACTERS and character.isprintable()
    )

    # A leading dot would hide the file; a trailing dot or space is invalid on
    # Windows and confusing everywhere else.
    return cleaned.strip(". ")
