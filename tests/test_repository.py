from typing import Any

import pytest

from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.markdown import render_recipe
from paprika_recipes.remote import RemoteRecipe
from paprika_recipes.repository import (
    Repository,
    RepositoryConfig,
    Status,
    safe_filename,
)


@pytest.fixture
def repository(tmp_path) -> Repository:
    return Repository.initialize(tmp_path)


def make_recipe(**overrides) -> RemoteRecipe:
    data: dict[str, Any] = {
        "name": "Khachapuri",
        "ingredients": "1 tsp salt\n1 cup water",
        "directions": "Combine.\n\nBake.",
    }
    data.update(overrides)

    return RemoteRecipe(**data)


def pull(repository: Repository, recipe: RemoteRecipe):
    return repository.store(recipe)


class TestInitialization:
    def test_creates_the_repository_directory(self, tmp_path):
        repository = Repository.initialize(tmp_path)

        assert repository.repository_dir.is_dir()
        assert repository.base_dir.is_dir()

    def test_refuses_a_directory_that_is_not_a_repository(self, tmp_path):
        with pytest.raises(PaprikaUserError, match="not a paprika recipe directory"):
            Repository(tmp_path)

    def test_round_trips_its_configuration(self, tmp_path):
        Repository.initialize(
            tmp_path, RepositoryConfig(account="me@example.com", domain="example.com")
        )

        config = Repository(tmp_path).config

        assert config.account == "me@example.com"
        assert config.domain == "example.com"

    def test_finds_a_repository_from_a_subdirectory(self, tmp_path):
        Repository.initialize(tmp_path)
        nested = tmp_path / "Desserts" / "Cookies"
        nested.mkdir(parents=True)

        assert Repository.find(nested).root == tmp_path.resolve()

    def test_reports_when_there_is_no_repository(self, tmp_path):
        with pytest.raises(PaprikaUserError, match="No paprika recipe directory"):
            Repository.find(tmp_path)


class TestChangeDetection:
    def test_a_freshly_pulled_recipe_is_unchanged(self, repository):
        pull(repository, make_recipe())

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert entry.changed_fields() == []

    def test_an_edited_recipe_is_modified(self, repository):
        path = pull(repository, make_recipe())
        path.write_text(
            path.read_text(encoding="utf-8").replace("Bake.", "Bake for 20 minutes."),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.status is Status.MODIFIED
        assert entry.changed_fields() == ["directions"]
        assert entry.recipe.directions == "Combine.\n\nBake for 20 minutes."

    def test_a_recipe_with_no_base_copy_is_added(self, repository):
        repository.write_working(make_recipe())

        (entry,) = repository.status()

        assert entry.status is Status.ADDED
        assert entry.base is None

    def test_a_deleted_file_is_reported(self, repository):
        path = pull(repository, make_recipe())
        path.unlink()

        (entry,) = repository.status()

        assert entry.status is Status.DELETED
        assert entry.path is None
        assert entry.base is not None

    def test_reports_only_the_fields_that_actually_changed(self, repository):
        path = pull(repository, make_recipe(rating=0, notes=""))
        path.write_text(
            path.read_text(encoding="utf-8").replace("rating: 0", "rating: 5"),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.changed_fields() == ["rating"]

    def test_ignores_the_servers_hash_when_diffing(self, repository):
        """Paprika's hash is its token, not a field the user can meaningfully edit."""
        path = pull(repository, make_recipe(hash="aaaa"))
        path.write_text(
            path.read_text(encoding="utf-8").replace("hash: aaaa", "hash: bbbb"),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.changed_fields() == []


class TestRenderCompareGuarantee:
    """The point of comparing rendered text rather than parsed fields.

    Detection must stay correct even when the round-trip is imperfect, so that
    a lossy field can never make untouched recipes look dirty.
    """

    def test_an_untouched_file_is_clean_even_when_a_field_is_lossy(
        self, repository, monkeypatch
    ):
        recipe = make_recipe()
        pull(repository, recipe)

        # Make the renderer lossy after the fact: from here on, parsing any
        # file yields a recipe whose directions do not match what was written.
        import paprika_recipes.repository as repository_module

        real_parse = repository_module.parse_recipe

        def lossy_parse(content, recipe_class):
            parsed = real_parse(content, recipe_class)
            parsed.directions = parsed.directions.upper()
            return parsed

        monkeypatch.setattr(repository_module, "parse_recipe", lossy_parse)

        (entry,) = repository.status()

        # Had we compared parsed fields, this would read as MODIFIED.
        assert entry.status is Status.UNCHANGED

    def test_detects_an_edit_even_when_it_parses_identically(self, repository):
        """Whitespace an editor might add still counts as touching the file."""
        path = pull(repository, make_recipe())
        path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

        (entry,) = repository.status()

        assert entry.status is Status.MODIFIED
        # ...but nothing meaningful actually changed, so there is nothing to push.
        assert entry.changed_fields() == []


class TestStore:
    def test_writes_both_the_working_file_and_the_base_copy(self, repository):
        recipe = make_recipe()

        path = repository.store(recipe)

        assert path.is_file()
        assert repository.read_base(recipe.uid) is not None

    def test_normalizes_before_writing_so_the_recipe_reads_as_unchanged(
        self, repository
    ):
        """A trailing newline must not leave the recipe permanently dirty."""
        repository.store(make_recipe(directions="Combine.\n\nBake.\n"))

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED

    def test_the_base_copy_renders_to_exactly_the_working_file(self, repository):
        """The invariant the whole change-detection scheme rests on."""
        recipe = make_recipe(notes="Best warm.\n")

        path = repository.store(recipe)
        base = repository.read_base(recipe.uid)

        assert base is not None
        assert path.read_text(encoding="utf-8") == render_recipe(base)


class TestWriteSafety:
    def test_refuses_to_write_a_recipe_it_could_not_read_back(
        self, repository, monkeypatch
    ):
        import paprika_recipes.repository as repository_module

        monkeypatch.setattr(
            repository_module, "find_lossy_fields", lambda recipe: ["directions"]
        )

        with pytest.raises(PaprikaUserError, match="could not be read back"):
            repository.write_working(make_recipe())

    def test_rejects_two_files_claiming_the_same_recipe(self, repository):
        recipe = make_recipe()
        repository.write_working(recipe)
        (repository.root / "Copy.md").write_text(
            render_recipe(recipe), encoding="utf-8"
        )

        with pytest.raises(PaprikaUserError, match="same recipe uid"):
            repository.status()

    def test_ignores_markdown_outside_the_working_tree(self, repository):
        (repository.repository_dir / "notes.md").write_text("hello", encoding="utf-8")

        assert repository.status() == []


class TestFileNaming:
    def test_names_a_file_after_the_recipe(self, repository):
        path = repository.write_working(make_recipe(name="Khachapuri"))

        assert path.name == "Khachapuri.md"

    def test_keeps_a_recipe_in_the_file_it_already_occupies(self, repository):
        recipe = make_recipe()
        original = repository.write_working(recipe)
        moved = repository.root / "Breads" / "Khachapuri.md"
        moved.parent.mkdir()
        original.rename(moved)

        assert repository.path_for(recipe) == moved

    def test_disambiguates_two_recipes_sharing_a_name(self, repository):
        first = repository.write_working(make_recipe(name="Cookies"))
        second = repository.write_working(make_recipe(name="Cookies"))

        assert first != second
        assert first.name == "Cookies.md"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Mom's Rice", "Mom's Rice"),
            ("Pasta / Noodles", "Pasta  Noodles"),
            ("Bánh Mì", "Bánh Mì"),
            (".hidden", "hidden"),
            ("What?!", "What!"),
        ],
    )
    def test_makes_names_safe_for_the_filesystem(self, name, expected):
        assert safe_filename(name) == expected

    def test_falls_back_to_the_uid_for_an_unusable_name(self, repository):
        path = repository.write_working(make_recipe(name="///", uid="ABC-123"))

        assert path.name == "ABC-123.md"
