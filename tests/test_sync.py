from dataclasses import replace
from typing import Any

import pytest

from paprika_recipes.commands.restore import matches
from paprika_recipes.remote import RemoteRecipe
from paprika_recipes.repository import Repository, Status
from paprika_recipes.sync import Action, Syncer, restore


class FakeAccount:
    """A paprika account that lives in memory.

    Recipes are stored as their `as_dict()` form so that handing one out gives
    the caller a copy, exactly as a real fetch would; nothing a test does to a
    returned recipe can reach back into the account.
    """

    def __init__(self, *recipes: RemoteRecipe):
        self.recipes: dict[str, dict[str, Any]] = {}
        self.notified = 0
        self.index_requests = 0

        for recipe in recipes:
            self.put(recipe)

    # -- Standing in for `Remote` -------------------------------------------

    def get_recipe_index(self) -> dict[str, str]:
        self.index_requests += 1

        return {uid: data["hash"] for uid, data in self.recipes.items()}

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe:
        return RemoteRecipe.from_dict(self.recipes[id])

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

        self.put(replace(recipe, **changes, hash=f"server-edit-{len(changes)}-{uid}"))

    def remove(self, uid: str) -> None:
        del self.recipes[uid]


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

    def test_refuses_to_overwrite_a_recipe_changed_on_both_sides(
        self, repository, account
    ):
        Syncer(repository, account).pull()
        edit_file(repository, "A", "1 tsp salt", "2 tsp salt")
        account.edit("A", notes="Now with notes.")

        report = Syncer(repository, account).pull()

        (conflict,) = report.conflicts
        assert conflict.name == "Recipe A"
        assert "ingredients" in conflict.detail
        # The user's edit is still there, untouched.
        assert "2 tsp salt" in repository.paths_by_uid()["A"].read_text()

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
