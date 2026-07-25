from dataclasses import replace
from typing import Any

import pytest

from paprika_recipes.commands.restore import matches
from paprika_recipes.exceptions import PaprikaUserError, RequestError
from paprika_recipes.remote import RemoteRecipe
from paprika_recipes.repository import Repository, RepositoryConfig, Status
from paprika_recipes.sync import Action, Syncer, restore


class FakeAccount:
    """A paprika account that lives in memory.

    Recipes are stored as their `as_dict()` form so that handing one out gives
    the caller a copy, exactly as a real fetch would; nothing a test does to a
    returned recipe can reach back into the account.
    """

    def __init__(self, *recipes: RemoteRecipe):
        self.recipes: dict[str, dict[str, Any]] = {}
        self.photos: dict[str, bytes] = {}
        self.notified = 0
        self.index_requests = 0
        self.photo_downloads = 0
        self.edits = 0

        for recipe in recipes:
            self.put(recipe)

    # -- Standing in for `Remote` -------------------------------------------

    def get_recipe_index(self) -> dict[str, str]:
        self.index_requests += 1

        return {uid: data["hash"] for uid, data in self.recipes.items()}

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe:
        return RemoteRecipe.from_dict(self.recipes[id])

    def download_photo(self, url: str) -> bytes:
        self.photo_downloads += 1

        try:
            return self.photos[url]
        except KeyError:
            raise RequestError(f"there is no photo at {url}")

    def upload_recipe(self, recipe: RemoteRecipe) -> RemoteRecipe:
        # Paprika rewrites the hash on every upload, and we cannot compute the
        # value it will choose, so the fake picks an arbitrary new one.
        return self.put(
            replace(recipe, hash=f"server-{len(self.recipes)}-{recipe.uid}")
        )

    def notify(self) -> None:
        self.notified += 1

    # -- Driving the fake from a test ---------------------------------------

    def put(self, recipe: RemoteRecipe) -> RemoteRecipe:
        self.recipes[recipe.uid] = recipe.as_dict()

        return recipe

    def edit(self, uid: str, **changes: Any) -> None:
        """Change a recipe the way another paprika client would."""
        recipe = RemoteRecipe.from_dict(self.recipes[uid])
        self.edits += 1

        self.put(replace(recipe, **changes, hash=f"server-edit-{self.edits}-{uid}"))

    def remove(self, uid: str) -> None:
        del self.recipes[uid]

    def give_photo(
        self, uid: str, data: bytes = b"jpeg bytes", version: int = 1
    ) -> str:
        """Attach a photo to a recipe the way the paprika app would."""
        name = f"{uid}-{version}.jpg"
        url = f"https://photos.example/{name}"

        self.photos[url] = data
        self.edit(uid, photo=name, photo_hash=f"photo-hash-{version}", photo_url=url)

        return name


def make_recipe(uid: str, **overrides: Any) -> RemoteRecipe:
    data: dict[str, Any] = {
        "uid": uid,
        "name": f"Recipe {uid}",
        "hash": f"server-{uid}",
        "ingredients": "1 tsp salt",
        "directions": "Combine.",
    }
    data.update(overrides)

    return RemoteRecipe(**data)


@pytest.fixture
def repository(tmp_path) -> Repository:
    return Repository.initialize(tmp_path)


@pytest.fixture
def account() -> FakeAccount:
    return FakeAccount(make_recipe("A"), make_recipe("B"))


def edit_file(repository: Repository, uid: str, old: str, new: str) -> None:
    """Edit a recipe file the way the user would."""
    path = repository.paths_by_uid()[uid]
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def actions(report) -> dict[str, Action]:
    return {change.name: change.action for change in report.changes}


class TestPullingIntoAnEmptyDirectory:
    def test_writes_every_recipe(self, repository, account):
        report = Syncer(repository, account).pull()

        assert actions(report) == {"Recipe A": Action.ADDED, "Recipe B": Action.ADDED}
        assert sorted(repository.paths_by_uid()) == ["A", "B"]

    def test_leaves_the_recipes_reading_as_unchanged(self, repository, account):
        Syncer(repository, account).pull()

        assert all(entry.status is Status.UNCHANGED for entry in repository.status())

    def test_skips_recipes_in_the_trash(self, repository, account):
        account.put(make_recipe("C", in_trash=True))

        report = Syncer(repository, account).pull()

        assert "Recipe C" not in actions(report)
        assert "C" not in repository.paths_by_uid()

    def test_writes_nothing_on_a_dry_run(self, repository, account):
        report = Syncer(repository, account).pull(dry_run=True)

        assert actions(report) == {"Recipe A": Action.ADDED, "Recipe B": Action.ADDED}
        assert repository.paths_by_uid() == {}


class TestPullingChanges:
    def test_fetches_only_the_recipes_whose_hash_moved(self, repository, account):
        Syncer(repository, account).pull()
        account.edit("A", notes="Now with notes.")

        fetched = []
        original = account.get_recipe_by_id

        def counting_fetch(id, hash):
            fetched.append(id)
            return original(id, hash)

        account.get_recipe_by_id = counting_fetch
        report = Syncer(repository, account).pull()

        assert fetched == ["A"]
        assert report.unchanged == 1

    def test_applies_a_change_from_the_server(self, repository, account):
        Syncer(repository, account).pull()
        account.edit("A", notes="Now with notes.")

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.UPDATED
        assert repository.read_base("A").notes == "Now with notes."

    def test_leaves_a_locally_edited_recipe_alone_when_the_server_has_not_moved(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        Syncer(repository, account).pull()

        (entry,) = (e for e in repository.status() if e.uid == "A")
        assert entry.recipe.ingredients == "2 tsp salt"

    def test_merges_changes_to_different_parts_of_a_recipe(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.edit("A", notes="Now with notes.")

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.MERGED

        (entry,) = (e for e in repository.status() if e.uid == "A")
        assert entry.recipe.ingredients == "2 tsp salt"
        assert entry.recipe.notes == "Now with notes."

    def test_a_merge_is_left_as_a_local_change_to_push(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.edit("A", notes="Now with notes.")
        Syncer(repository, account).pull()

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["ingredients"] == "2 tsp salt"
        assert account.recipes["A"]["notes"] == "Now with notes."

    def test_a_cosmetic_local_edit_does_not_block_an_update(self, repository, account):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
        account.edit("A", notes="Now with notes.")

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.UPDATED

    def test_preserves_a_users_own_frontmatter_across_an_update(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "---\n", "---\ntags:\n- dinner\n", 1
            ),
            encoding="utf-8",
        )
        account.edit("A", notes="Now with notes.")

        Syncer(repository, account).pull()

        assert "tags:" in path.read_text(encoding="utf-8")
        assert repository.read_working(path).notes == "Now with notes."


class TestPullingRemovals:
    def test_removes_a_recipe_that_is_gone_from_the_server(self, repository, account):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        account.remove("A")

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.REMOVED
        assert not path.exists()
        assert repository.read_base("A") is None

    def test_removes_a_recipe_the_server_moved_to_the_trash(self, repository, account):
        Syncer(repository, account).pull()
        account.edit("A", in_trash=True)

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.REMOVED

    def test_keeps_a_locally_edited_recipe_the_server_has_dropped(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.remove("A")

        report = Syncer(repository, account).pull()

        (conflict,) = report.conflicts
        assert "no longer on the server" in conflict.detail
        assert repository.paths_by_uid()["A"].exists()

    def test_forgets_a_recipe_deleted_on_both_sides(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        account.remove("A")

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.REMOVED
        assert repository.base_uids() == {"B"}

    def test_removes_nothing_on_a_dry_run(self, repository, account):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        account.remove("A")

        Syncer(repository, account).pull(dry_run=True)

        assert path.exists()


class TestPushing:
    def test_sends_a_locally_edited_recipe(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["ingredients"] == "2 tsp salt"

    def test_creates_a_recipe_the_server_does_not_have(self, repository, account):
        Syncer(repository, account).pull()
        repository.write_working(make_recipe("C", name="Brand New"))

        report = Syncer(repository, account).push()

        assert actions(report)["Brand New"] is Action.CREATED
        assert account.recipes["C"]["name"] == "Brand New"

    def test_leaves_the_pushed_recipe_reading_as_unchanged(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        Syncer(repository, account).push()

        assert all(entry.status is Status.UNCHANGED for entry in repository.status())

    def test_records_the_servers_new_hash_so_the_next_pull_is_quiet(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        Syncer(repository, account).push()

        report = Syncer(repository, account).pull()

        assert not report.changes
        assert report.unchanged == 2

    def test_tells_paprika_to_notify_its_apps(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        Syncer(repository, account).push()

        assert account.notified == 1

    def test_says_nothing_to_the_server_when_nothing_changed(self, repository, account):
        Syncer(repository, account).pull()

        report = Syncer(repository, account).push()

        assert not report.changes
        assert account.notified == 0

    def test_refuses_to_overwrite_a_recipe_the_server_has_moved(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.edit("A", notes="Changed elsewhere.")

        report = Syncer(repository, account).push()

        (conflict,) = report.conflicts
        assert "changed on the server" in conflict.detail
        assert account.recipes["A"]["ingredients"] == "1 tsp salt"

    def test_does_not_send_a_recipe_whose_file_only_looks_different(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

        report = Syncer(repository, account).push()

        (skipped,) = report.of(Action.SKIPPED)
        assert "how the file is written" in skipped.detail
        assert account.notified == 0

    def test_refuses_an_untracked_recipe_whose_uid_is_already_taken(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        repository.delete_base("A")

        report = Syncer(repository, account).push()

        (conflict,) = report.conflicts
        assert "already on the server" in conflict.detail

    def test_sends_nothing_on_a_dry_run(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = Syncer(repository, account).push(dry_run=True)

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["ingredients"] == "1 tsp salt"
        assert account.notified == 0


class TestPushingDeletions:
    """Deleting a file moves the recipe into Paprika's trash, not oblivion."""

    def test_trashes_a_recipe_whose_file_was_deleted(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.TRASHED
        assert account.recipes["A"]["in_trash"] is True

    def test_keeps_everything_else_about_the_recipe(self, repository, account):
        """Trashing is a flag, so the recipe is still there to be recovered."""
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        Syncer(repository, account).push()

        assert account.recipes["A"]["ingredients"] == "1 tsp salt"

    def test_stops_tracking_the_trashed_recipe(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        Syncer(repository, account).push()

        assert repository.base_uids() == {"B"}

    def test_does_not_write_the_file_back_out(self, repository, account):
        """The push refresh must not resurrect what was just deleted."""
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.unlink()

        Syncer(repository, account).push()

        assert not path.exists()

    def test_leaves_the_directory_quiet_afterwards(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        Syncer(repository, account).push()

        report = Syncer(repository, account).pull()

        assert not report.changes

    def test_tells_paprika_to_notify_its_apps(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        Syncer(repository, account).push()

        assert account.notified == 1

    def test_refuses_when_the_server_has_changed_it_since(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        account.edit("A", notes="Changed elsewhere.")

        report = Syncer(repository, account).push()

        (conflict,) = report.conflicts
        assert "since changed on the server" in conflict.detail
        assert account.recipes["A"]["in_trash"] is False
        # Still restorable, because the base copy was not thrown away.
        assert repository.read_base("A") is not None

    def test_just_forgets_a_recipe_the_server_no_longer_has(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        account.remove("A")

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.REMOVED
        assert repository.base_uids() == {"B"}

    def test_trashes_nothing_on_a_dry_run(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        report = Syncer(repository, account).push(dry_run=True)

        assert actions(report)["Recipe A"] is Action.TRASHED
        assert account.recipes["A"]["in_trash"] is False
        assert repository.read_base("A") is not None


class TestRestoring:
    def test_undoes_an_edit(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = restore(repository, repository.status())

        assert actions(report)["Recipe A"] is Action.RESTORED
        assert "1 tsp salt" in repository.paths_by_uid()["A"].read_text()

    def test_brings_back_a_deleted_file(self, repository, account):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.unlink()

        report = restore(repository, repository.status())

        assert actions(report)["Recipe A"] is Action.RESTORED
        assert path.exists()

    def test_leaves_the_recipe_reading_as_unchanged(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        restore(repository, repository.status())

        assert all(entry.status is Status.UNCHANGED for entry in repository.status())

    def test_means_a_later_push_has_nothing_to_say(self, repository, account):
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        restore(repository, repository.status())

        report = Syncer(repository, account).push()

        assert not report.changes
        assert account.recipes["A"]["in_trash"] is False

    def test_refuses_to_delete_a_recipe_that_was_never_pulled(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        path = repository.write_working(make_recipe("C", name="Brand New"))

        report = restore(repository, repository.status())

        (skipped,) = report.of(Action.SKIPPED)
        assert "never pulled" in skipped.detail
        assert path.exists()

    def test_keeps_a_users_own_frontmatter(self, repository, account):
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.write_text(
            path.read_text(encoding="utf-8")
            .replace("---\n", "---\ntags:\n- dinner\n", 1)
            .replace("1 tsp salt", "2 tsp salt"),
            encoding="utf-8",
        )

        restore(repository, repository.status())

        assert "tags:" in path.read_text(encoding="utf-8")
        assert "1 tsp salt" in path.read_text(encoding="utf-8")

    def test_leaves_untouched_recipes_alone(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = restore(repository, repository.status())

        assert len(report.changes) == 1
        assert report.unchanged == 1


class TestProgressReporting:
    def test_names_each_recipe_it_touches(self, repository, account):
        seen: list[str] = []

        Syncer(repository, account, seen.append).pull()

        assert sorted(seen) == ["Recipe A", "Recipe B"]


class TestRestoreTargets:
    """Naming a recipe on the command line."""

    @pytest.fixture
    def entry(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        (entry,) = (e for e in repository.status() if e.uid == "A")

        return entry

    def test_matches_a_title(self, entry):
        assert matches(entry, "Recipe A")

    def test_matches_a_title_regardless_of_case(self, entry):
        assert matches(entry, "recipe a")

    def test_matches_a_uid(self, entry):
        assert matches(entry, "A")

    def test_matches_a_path(self, entry):
        assert matches(entry, str(entry.path))

    def test_does_not_match_something_else(self, entry):
        assert not matches(entry, "Recipe B")

    def test_matches_a_deleted_recipe_by_title(self, repository, account):
        """The case that matters most: there is no file left to name."""
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        (entry,) = (e for e in repository.status() if e.uid == "A")

        assert entry.path is None
        assert matches(entry, "Recipe A")


class TestMerging:
    """Both sides moved. See `paprika_recipes.merge` for the rules."""

    def diverge(self, repository, account, *, local: str, remote: str) -> None:
        """Change the same recipe's directions on both sides."""
        Syncer(repository, account).pull()
        edit_file(repository, "A", "Combine.", local)
        account.edit("A", directions=remote)

    def working(self, repository):
        (entry,) = (e for e in repository.status() if e.uid == "A")

        return entry

    def test_keeps_both_edits_when_they_do_not_overlap(self, repository, account):
        account.put(make_recipe("A", directions="One.\nTwo.\nThree."))
        Syncer(repository, account).pull()
        edit_file(repository, "A", "One.", "One (mine).")
        account.edit("A", directions="One.\nTwo.\nThree (theirs).")

        Syncer(repository, account).pull()

        assert self.working(repository).recipe.directions == (
            "One (mine).\nTwo.\nThree (theirs)."
        )

    def test_marks_an_overlapping_edit_as_a_conflict(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")

        report = Syncer(repository, account).pull()

        (conflict,) = report.conflicts
        assert "directions" in conflict.detail
        assert "conflict markers" in conflict.detail

    def test_leaves_both_versions_in_the_file(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")

        Syncer(repository, account).pull()

        directions = self.working(repository).recipe.directions
        assert "Mine." in directions
        assert "Theirs." in directions
        assert "<<<<<<< yours" in directions

    def test_refuses_to_push_an_unresolved_conflict(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")
        Syncer(repository, account).pull()

        report = Syncer(repository, account).push()

        (conflict,) = report.conflicts
        assert "unresolved conflict markers" in conflict.detail
        assert "<<<<<<<" not in account.recipes["A"]["directions"]

    def test_pushes_once_the_markers_are_gone(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")
        Syncer(repository, account).pull()

        path = repository.paths_by_uid()["A"]
        path.write_text(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if not line.startswith(("<<<<<<<", "=======", ">>>>>>>", "Theirs."))
            ),
            encoding="utf-8",
        )

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["directions"] == "Mine."

    def test_a_conflict_can_be_thrown_away_with_restore(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")
        Syncer(repository, account).pull()

        restore(repository, repository.status())

        assert self.working(repository).recipe.directions == "Theirs."
        assert self.working(repository).status is Status.UNCHANGED

    def test_refuses_a_recipe_whose_rating_moved_on_both_sides(
        self, repository, account
    ):
        """A rating cannot hold both answers, so nothing is touched."""
        Syncer(repository, account).pull()
        edit_file(repository, "A", "rating: 0", "rating: 5")
        account.edit("A", rating=3)

        report = Syncer(repository, account).pull()

        (conflict,) = report.conflicts
        assert "rating" in conflict.detail
        assert self.working(repository).recipe.rating == 5
        assert repository.read_base("A").rating == 0

    def test_takes_the_servers_value_for_a_field_only_it_changed(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.edit("A", rating=3)

        Syncer(repository, account).pull()

        assert self.working(repository).recipe.rating == 3
        assert self.working(repository).recipe.ingredients == "2 tsp salt"

    def test_changes_nothing_on_a_dry_run(self, repository, account):
        self.diverge(repository, account, local="Mine.", remote="Theirs.")

        Syncer(repository, account).pull(dry_run=True)

        assert self.working(repository).recipe.directions == "Mine."


def write_untracked(repository: Repository, name: str, **frontmatter: str) -> None:
    """Write a recipe file by hand, the way someone would in their vault."""
    lines = [f"{key}: {value}" for key, value in frontmatter.items()]

    (repository.root / f"{name}.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n\n"
        f"# {name}\n\n## Ingredients\n\n- 1 tsp salt\n",
        encoding="utf-8",
    )


class TestPushingARecipeSomebodyWrote:
    def test_creates_it_on_the_server(self, repository, account):
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine")

        report = Syncer(repository, account).push()

        assert actions(report)["Mine"] is Action.CREATED
        assert len(account.recipes) == 3

    def test_gives_it_a_uid_of_its_own(self, repository, account):
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine")

        Syncer(repository, account).push()

        assert "uid:" in (repository.root / "Mine.md").read_text(encoding="utf-8")

    def test_creates_it_only_once(self, repository, account):
        """The bug this whole arrangement exists to prevent.

        With a uid invented at parse time rather than written to the file, the
        recipe was uploaded, re-read under a *different* uid, written out as a
        second file, and uploaded again on every push thereafter.
        """
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine")

        Syncer(repository, account).push()
        report = Syncer(repository, account).push()

        assert not report.changes
        assert len(account.recipes) == 3
        assert len(list(repository.working_paths())) == 3

    def test_writes_nothing_during_a_dry_run(self, repository, account):
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine")
        before = (repository.root / "Mine.md").read_text(encoding="utf-8")

        report = Syncer(repository, account).push(dry_run=True)

        assert actions(report)["Mine"] is Action.CREATED
        assert (repository.root / "Mine.md").read_text(encoding="utf-8") == before
        assert len(account.recipes) == 2


class TestRefusingToActOnADirectoryItCannotRead:
    def test_refuses_a_file_holding_a_uid_it_cannot_read(self, repository, account):
        """What a mis-set `frontmatter_prefix` looks like from in here."""
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine", paprika_uid="SOME-UID")

        with pytest.raises(PaprikaUserError, match="frontmatter_prefix"):
            Syncer(repository, account).push()

    @pytest.mark.parametrize("key", ["paprika_uid", "paprika-uid", "UID"])
    def test_recognises_a_uid_however_it_was_spelled(self, repository, account, key):
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine", **{key: "SOME-UID"})

        with pytest.raises(PaprikaUserError, match="frontmatter_prefix"):
            Syncer(repository, account).push()

    def test_allows_a_recipe_that_never_claimed_an_identity(self, repository, account):
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine", tags="dinner")

        assert Syncer(repository, account).push().changes

    def test_ignores_a_vaults_own_uuid_field(self, repository, account):
        """`uuid:` is somebody else's field, not a mangling of ours."""
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine", uuid="1234")

        assert Syncer(repository, account).push().changes

    def test_refuses_when_every_recipe_lost_its_file(self, repository, account):
        Syncer(repository, account).pull()

        for path in list(repository.working_paths()):
            path.unlink()

        write_untracked(repository, "Mine")

        with pytest.raises(PaprikaUserError, match="stopped being readable"):
            Syncer(repository, account).push()

    def test_still_allows_deleting_every_recipe(self, repository, account):
        """The state the guard must not be confused by."""
        Syncer(repository, account).pull()

        for path in list(repository.working_paths()):
            path.unlink()

        report = Syncer(repository, account).push()

        assert set(actions(report).values()) == {Action.TRASHED}

    def test_allows_a_new_recipe_alongside_one_deletion(self, repository, account):
        """One deleted and one written is an ordinary afternoon."""
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()
        write_untracked(repository, "Mine")

        report = Syncer(repository, account).push()

        assert actions(report)["Mine"] is Action.CREATED
        assert actions(report)["Recipe A"] is Action.TRASHED


class TestSyncingADirectoryWithAFrontmatterPrefix:
    @pytest.fixture
    def repository(self, tmp_path) -> Repository:
        return Repository.initialize(
            tmp_path, RepositoryConfig(frontmatter_prefix="paprika_")
        )

    def test_pulls_and_pushes_as_usual(self, repository, account):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["ingredients"] == "2 tsp salt"

    def test_refuses_a_file_written_without_the_prefix(self, repository, account):
        """A file from an unprefixed clone, dropped into a prefixed one."""
        Syncer(repository, account).pull()
        write_untracked(repository, "Mine", uid="SOME-UID")

        with pytest.raises(PaprikaUserError, match="frontmatter_prefix"):
            Syncer(repository, account).push()


class TestPhotosComeDownWithAPull:
    def test_the_photo_lands_in_attachments(self, repository, account):
        account.give_photo("A", b"khachapuri glamour shot")

        Syncer(repository, account).pull()

        photo = repository.attachments_dir / "A-1.jpg"
        assert photo.read_bytes() == b"khachapuri glamour shot"

    def test_the_file_embeds_it(self, repository, account):
        account.give_photo("A")

        Syncer(repository, account).pull()

        content = repository.paths_by_uid()["A"].read_text(encoding="utf-8")
        assert "](attachments/A-1.jpg)" in content
        assert "photo" not in content.split("---")[1]

    def test_an_unchanged_recipe_is_not_downloaded_again(self, repository, account):
        account.give_photo("A")
        Syncer(repository, account).pull()

        Syncer(repository, account).pull()

        assert account.photo_downloads == 1

    def test_an_attachment_tidied_away_by_hand_is_healed(self, repository, account):
        """A vault user pruning "unused" files must not break the embed forever."""
        account.give_photo("A")
        Syncer(repository, account).pull()
        (repository.attachments_dir / "A-1.jpg").unlink()

        Syncer(repository, account).pull()

        assert (repository.attachments_dir / "A-1.jpg").is_file()

    def test_a_replaced_photo_replaces_the_attachment(self, repository, account):
        account.give_photo("A", b"old", version=1)
        Syncer(repository, account).pull()
        account.give_photo("A", b"new", version=2)

        Syncer(repository, account).pull()

        assert (repository.attachments_dir / "A-2.jpg").read_bytes() == b"new"
        assert not (repository.attachments_dir / "A-1.jpg").exists()
        assert "A-2.jpg" in repository.paths_by_uid()["A"].read_text(encoding="utf-8")

    def test_a_photo_removed_in_the_app_removes_the_attachment(
        self, repository, account
    ):
        account.give_photo("A")
        Syncer(repository, account).pull()
        account.edit("A", photo="", photo_hash="", photo_url=None)

        Syncer(repository, account).pull()

        assert not (repository.attachments_dir / "A-1.jpg").exists()
        assert "![" not in repository.paths_by_uid()["A"].read_text(encoding="utf-8")

    def test_a_removed_recipe_takes_its_attachment_with_it(self, repository, account):
        account.give_photo("A")
        Syncer(repository, account).pull()
        account.remove("A")

        Syncer(repository, account).pull()

        assert not (repository.attachments_dir / "A-1.jpg").exists()

    def test_a_dry_run_downloads_nothing(self, repository, account):
        account.give_photo("A")

        Syncer(repository, account).pull(dry_run=True)

        assert account.photo_downloads == 0
        assert not repository.attachments_dir.exists()

    def test_a_failed_download_does_not_stop_the_pull(self, repository, account):
        account.give_photo("A")
        del account.photos["https://photos.example/A-1.jpg"]

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.ADDED
        (skipped,) = report.of(Action.SKIPPED)
        assert "could not be downloaded" in skipped.detail
        assert sorted(repository.paths_by_uid()) == ["A", "B"]

    def test_a_failed_download_is_retried_on_the_next_pull(self, repository, account):
        account.give_photo("A", b"eventually")
        url = "https://photos.example/A-1.jpg"
        data = account.photos.pop(url)
        Syncer(repository, account).pull()

        account.photos[url] = data
        report = Syncer(repository, account).pull()

        assert not report.of(Action.SKIPPED)
        assert (repository.attachments_dir / "A-1.jpg").read_bytes() == b"eventually"


class TestPhotosStayTheServersOnAPush:
    """Until add/remove lands, no edit to a file can change a photo."""

    def delete_embed(self, repository, uid: str) -> None:
        path = repository.paths_by_uid()[uid]
        path.write_text(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if not line.startswith("![")
            ),
            encoding="utf-8",
        )

    def test_a_deleted_embed_alone_is_nothing_to_push(self, repository, account):
        account.give_photo("A")
        Syncer(repository, account).pull()
        self.delete_embed(repository, "A")

        report = Syncer(repository, account).push()

        (skipped,) = report.of(Action.SKIPPED)
        assert "how the file is written" in skipped.detail
        assert account.recipes["A"]["photo"] == "A-1.jpg"

    def test_an_edit_beside_a_deleted_embed_keeps_the_servers_photo(
        self, repository, account
    ):
        account.give_photo("A")
        Syncer(repository, account).pull()
        self.delete_embed(repository, "A")
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        report = Syncer(repository, account).push()

        assert actions(report)["Recipe A"] is Action.UPLOADED
        assert account.recipes["A"]["ingredients"] == "2 tsp salt"
        assert account.recipes["A"]["photo"] == "A-1.jpg"
        assert "photo" in report.of(Action.UPLOADED)[0].detail

    def test_the_push_refresh_restores_the_embed(self, repository, account):
        """After a push, the file goes back to saying what the server says."""
        account.give_photo("A")
        Syncer(repository, account).pull()
        self.delete_embed(repository, "A")
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")

        Syncer(repository, account).push()

        content = repository.paths_by_uid()["A"].read_text(encoding="utf-8")
        assert "](attachments/A-1.jpg)" in content

    def test_a_hand_written_embed_is_not_uploaded(self, repository, account):
        Syncer(repository, account).pull()
        (repository.root / "Mine.md").write_text(
            "---\ntags: [dinner]\n---\n\n# Mine\n\n"
            "![my dinner](attachments/dinner.jpg)\n\n"
            "## Ingredients\n\n- 1 tsp salt\n",
            encoding="utf-8",
        )

        report = Syncer(repository, account).push()

        assert actions(report)["Mine"] is Action.CREATED
        created = next(
            data for data in account.recipes.values() if data["name"] == "Mine"
        )
        assert created["photo"] == ""
        assert "photo" in report.of(Action.CREATED)[0].detail

    def test_a_trashed_recipe_takes_its_attachment_with_it(self, repository, account):
        account.give_photo("A")
        Syncer(repository, account).pull()
        repository.paths_by_uid()["A"].unlink()

        Syncer(repository, account).push()

        assert not (repository.attachments_dir / "A-1.jpg").exists()
        assert repository.read_photo_state("A") is None


class TestPhotosAndMerges:
    def test_a_merge_keeps_the_servers_photo(self, repository, account):
        account.give_photo("A", version=1)
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.give_photo("A", b"newer", version=2)

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.MERGED
        content = repository.paths_by_uid()["A"].read_text(encoding="utf-8")
        assert "](attachments/A-2.jpg)" in content
        assert (repository.attachments_dir / "A-2.jpg").read_bytes() == b"newer"

    def test_a_deleted_embed_does_not_conflict_with_a_new_photo(
        self, repository, account
    ):
        """Photo changes cannot conflict while the server owns them."""
        account.give_photo("A", version=1)
        Syncer(repository, account).pull()

        path = repository.paths_by_uid()["A"]
        path.write_text(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if not line.startswith("![")
            ).replace("1 tsp salt", "2 tsp salt"),
            encoding="utf-8",
        )
        account.give_photo("A", version=2)

        report = Syncer(repository, account).pull()

        assert actions(report)["Recipe A"] is Action.MERGED
        assert "2 tsp salt" in path.read_text(encoding="utf-8")


class TestRestoringPhotos:
    def test_restore_brings_the_embed_back(self, repository, account):
        account.give_photo("A")
        Syncer(repository, account).pull()
        path = repository.paths_by_uid()["A"]
        path.write_text(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if not line.startswith("![")
            ),
            encoding="utf-8",
        )

        restore(repository, repository.status())

        assert "](attachments/A-1.jpg)" in path.read_text(encoding="utf-8")
