import json
from pathlib import Path
from typing import Any

import pytest

from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.markdown import DocumentFormat, render_recipe
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


def add_frontmatter(path: Path, line: str) -> None:
    """Add a line of the user's own frontmatter to a recipe file."""
    path.write_text(
        path.read_text(encoding="utf-8").replace("---\n", f"---\n{line}\n", 1),
        encoding="utf-8",
    )


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

    def test_a_recipe_with_carriage_returns_reads_as_unchanged(self, repository):
        """A `\r` written to disk is read back as `\n`, so it must never be written.

        Paprika's Windows client saves `\r\n` and older clients saved bare
        `\r`; either would leave the recipe permanently modified otherwise.
        """
        repository.store(
            make_recipe(
                ingredients="1 tsp salt\r\n1 cup water",
                directions="Combine.\r\rBake.",
            )
        )

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert entry.recipe.directions == "Combine.\n\nBake."

    def test_a_recipe_with_null_text_fields_reads_as_unchanged(self, repository):
        """Paprika sends `null` for a recipe that has no description."""
        repository.store(make_recipe(description=None, notes=None))

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED

    def test_a_base_copy_written_before_normalization_reads_as_unchanged(
        self, repository
    ):
        """3.0.0 wrote Paprika's `\r`s and `null`s straight into the base copy.

        The server's copy has not moved, so no pull will ever rewrite that
        base; it has to read as clean on its own, or the recipe stays
        modified forever after an upgrade.
        """
        recipe = make_recipe(
            description=None, directions="Combine.\r\n\r\nBake.", uid="legacy"
        )
        path = repository.store(recipe)

        # Put both files back the way 3.0.0 would have left them.
        repository.base_path_for(recipe.uid).write_text(
            json.dumps(recipe.as_dict()), encoding="utf-8"
        )
        path.write_bytes(render_recipe(recipe).encode("utf-8"))

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED

    def test_the_base_copy_renders_to_exactly_the_working_file(self, repository):
        """The invariant the whole change-detection scheme rests on."""
        recipe = make_recipe(notes="Best warm.\n")

        path = repository.store(recipe)
        base = repository.read_base(recipe.uid)

        assert base is not None
        assert path.read_text(encoding="utf-8") == render_recipe(base)


class TestUserFrontmatter:
    """A recipe file may live in a vault whose frontmatter is not all ours."""

    def test_a_users_own_frontmatter_is_not_an_edit_to_the_recipe(self, repository):
        path = pull(repository, make_recipe())
        add_frontmatter(path, "tags: [dinner]")

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED

    def test_a_users_own_frontmatter_survives_a_later_pull(self, repository):
        recipe = make_recipe()
        path = pull(repository, recipe)
        add_frontmatter(path, "tags: [dinner]")

        repository.store(make_recipe(uid=recipe.uid, notes="Updated upstream."))

        assert "tags:" in path.read_text(encoding="utf-8")
        assert repository.read_working(path).notes == "Updated upstream."

    def test_an_edit_is_still_detected_alongside_extra_frontmatter(self, repository):
        path = pull(repository, make_recipe())
        add_frontmatter(path, "tags: [dinner]")
        path.write_text(
            path.read_text(encoding="utf-8").replace("rating: 0", "rating: 5"),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.status is Status.MODIFIED
        assert entry.changed_fields() == ["rating"]


class TestUserSections:
    """A `## ` section of the user's own, added to a recipe file."""

    def add_section(self, path: Path) -> None:
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "## Directions", "## Substitutions\n\nUse butter.\n\n## Directions"
            ),
            encoding="utf-8",
        )

    def test_is_not_an_edit_to_the_recipe(self, repository):
        path = pull(repository, make_recipe())
        self.add_section(path)

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert not entry.has_local_changes()

    def test_does_not_leak_into_a_recipe_field(self, repository):
        path = pull(repository, make_recipe())
        self.add_section(path)

        recipe = repository.read_working(path)

        assert recipe.ingredients == "1 tsp salt\n1 cup water"
        assert "Substitutions" not in str(recipe.as_dict())

    def test_survives_a_later_pull(self, repository):
        recipe = make_recipe()
        path = pull(repository, recipe)
        self.add_section(path)

        repository.store(make_recipe(uid=recipe.uid, notes="Updated upstream."))

        assert "## Substitutions" in path.read_text(encoding="utf-8")
        assert repository.read_working(path).notes == "Updated upstream."

    def test_an_edit_beside_it_is_still_detected(self, repository):
        path = pull(repository, make_recipe())
        self.add_section(path)
        path.write_text(
            path.read_text(encoding="utf-8").replace("1 tsp salt", "2 tsp salt"),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.changed_fields() == ["ingredients"]
        assert entry.recipe.ingredients == "2 tsp salt\n1 cup water"


class TestLocalChanges:
    """`has_local_changes` asks whether the *server* would care."""

    def test_cosmetic_edits_do_not_count(self, repository):
        path = pull(repository, make_recipe())
        path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

        (entry,) = repository.status()

        assert entry.status is Status.MODIFIED
        assert not entry.has_local_changes()

    def test_a_real_edit_counts(self, repository):
        path = pull(repository, make_recipe())
        path.write_text(
            path.read_text(encoding="utf-8").replace("Bake.", "Broil."),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.has_local_changes()

    def test_an_untracked_recipe_counts(self, repository):
        repository.write_working(make_recipe())

        (entry,) = repository.status()

        assert entry.has_local_changes()

    def test_a_deleted_recipe_counts(self, repository):
        pull(repository, make_recipe()).unlink()

        (entry,) = repository.status()

        assert entry.has_local_changes()


class TestWriteSafety:
    def test_refuses_to_write_a_recipe_it_could_not_read_back(
        self, repository, monkeypatch
    ):
        monkeypatch.setattr(
            DocumentFormat,
            "find_lossy_fields",
            lambda self, recipe, extras=None: ["directions"],
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


def write_by_hand(repository: Repository, name: str, extra: str = "") -> Path:
    """Write a recipe file with no uid in it, the way a person would."""
    path = repository.root / f"{name}.md"
    path.write_text(
        f"---\n{extra}\n---\n\n# {name}\n\n## Ingredients\n\n- 1 tsp salt\n",
        encoding="utf-8",
    )

    return path


class TestRecipesWithNoUid:
    def test_reads_back_the_same_way_every_time(self, repository):
        """A uid invented at parse time would differ on every read.

        Which made "this file has no identity" indistinguishable from "this
        file has one", and silently so.
        """
        write_by_hand(repository, "Mine")

        first = repository.status()[0]
        second = repository.status()[0]

        assert first.uid == second.uid == ""

    def test_are_listed_rather_than_ignored(self, repository):
        write_by_hand(repository, "Mine")

        entries = repository.status()

        assert len(entries) == 1
        assert entries[0].status is Status.ADDED
        assert entries[0].untracked
        assert entries[0].name == "Mine"

    def test_are_kept_apart_from_the_tracked_ones(self, repository):
        pull(repository, make_recipe(uid="A"))
        write_by_hand(repository, "Mine")

        tracked, untracked = repository.scan()

        assert set(tracked) == {"A"}
        assert [path.name for path in untracked] == ["Mine.md"]

    def test_do_not_collide_with_each_other(self, repository):
        write_by_hand(repository, "Mine")
        write_by_hand(repository, "Yours")

        assert len(repository.status()) == 2


class TestAdopting:
    def test_writes_a_uid_into_the_file(self, repository):
        path = write_by_hand(repository, "Mine")

        adopted = repository.adopt(repository.status()[0])

        assert adopted.uid
        assert adopted.uid in path.read_text(encoding="utf-8")

    def test_makes_the_recipe_identifiable_from_then_on(self, repository):
        write_by_hand(repository, "Mine")

        adopted = repository.adopt(repository.status()[0])

        assert repository.paths_by_uid() == {adopted.uid: repository.root / "Mine.md"}

    def test_keeps_what_the_file_holds_of_its_own(self, repository):
        path = write_by_hand(repository, "Mine", extra="tags:\n- dinner")

        repository.adopt(repository.status()[0])

        assert "dinner" in path.read_text(encoding="utf-8")

    def test_leaves_an_already_tracked_recipe_alone(self, repository):
        """Nothing calls it that way, but a uid must never be reassigned."""
        pull(repository, make_recipe(uid="A"))
        entry = repository.status()[0]

        assert entry.uid == "A"
        assert not entry.untracked


class TestADirectoryWithAFrontmatterPrefix:
    @pytest.fixture
    def repository(self, tmp_path) -> Repository:
        return Repository.initialize(
            tmp_path, RepositoryConfig(frontmatter_prefix="paprika_")
        )

    def test_writes_its_files_with_the_prefix(self, repository):
        path = pull(repository, make_recipe(rating=4))

        assert "paprika_rating: 4" in path.read_text(encoding="utf-8")

    def test_reads_them_back_unchanged(self, repository):
        pull(repository, make_recipe(rating=4))

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert entry.recipe.rating == 4

    def test_leaves_a_vaults_own_field_out_of_the_recipe(self, repository):
        path = pull(repository, make_recipe(rating=4))
        add_frontmatter(path, "rating: 1")

        (entry,) = repository.status()

        assert entry.recipe.rating == 4
        assert entry.extras.frontmatter == {"rating": 1}
        assert entry.changed_fields() == []

    def test_keeps_the_prefix_out_of_the_base_copies(self, repository):
        """Those are ours; nothing else ever reads them."""
        recipe = make_recipe()
        pull(repository, recipe)

        stored = repository.base_path_for(recipe.uid).read_text(encoding="utf-8")

        assert '"uid"' in stored
        assert "paprika_" not in stored

    def test_survives_being_reopened(self, repository):
        """The prefix has to come back off disk, not out of the clone command."""
        pull(repository, make_recipe(rating=4))

        (entry,) = Repository(repository.root).status()

        assert entry.status is Status.UNCHANGED


class TestPhotoStorage:
    """Attachments on disk, and the record of what we downloaded."""

    JPEG = b"\xff\xd8\xff\xe0 not really a jpeg"

    def test_writes_the_photo_into_attachments(self, repository):
        path = repository.write_photo("A", "A-1.jpg", "hash-1", self.JPEG)

        assert path == repository.attachments_dir / "A-1.jpg"
        assert path.read_bytes() == self.JPEG

    def test_remembers_what_it_wrote(self, repository):
        repository.write_photo("A", "A-1.jpg", "hash-1", self.JPEG)

        state = repository.read_photo_state("A")

        assert state.photo == "A-1.jpg"
        assert state.photo_hash == "hash-1"
        # Recorded for the day photos become editable: it is what will tell
        # an attachment the user replaced from the one we downloaded.
        assert len(state.content_hash) == 64

    def test_a_replaced_photo_does_not_leave_the_old_file_behind(self, repository):
        repository.write_photo("A", "A-1.jpg", "hash-1", self.JPEG)
        repository.write_photo("A", "A-2.jpg", "hash-2", self.JPEG)

        assert not (repository.attachments_dir / "A-1.jpg").exists()
        assert (repository.attachments_dir / "A-2.jpg").is_file()

    def test_dropping_a_photo_removes_the_file_and_the_record(self, repository):
        repository.write_photo("A", "A-1.jpg", "hash-1", self.JPEG)

        repository.drop_photo("A")

        assert not (repository.attachments_dir / "A-1.jpg").exists()
        assert repository.read_photo_state("A") is None

    def test_dropping_a_photo_that_was_never_there_is_fine(self, repository):
        repository.drop_photo("A")

    def test_knows_nothing_about_a_photo_it_never_wrote(self, repository):
        assert repository.read_photo_state("A") is None

    @pytest.mark.parametrize("name", ["../escape.jpg", "a/b.jpg", "..", ".", ""])
    def test_refuses_a_photo_name_that_would_leave_attachments(self, repository, name):
        with pytest.raises(PaprikaUserError, match="not a name"):
            repository.attachment_path(name)


class TestPhotoChangeDetection:
    """The embed line, and the bytes behind it, are edits like any other."""

    def photographed(self, **overrides):
        data = {
            "photo": "A-1.jpg",
            "photo_hash": "hash-1",
            "photo_url": "https://photos.example/A-1.jpg",
        }
        data.update(overrides)

        return make_recipe(**data)

    def test_a_pulled_photo_reads_as_unchanged(self, repository):
        pull(repository, self.photographed())

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert "](attachments/A-1.jpg)" in entry.path.read_text(encoding="utf-8")

    def test_a_deleted_embed_is_a_photo_removal(self, repository):
        path = pull(repository, self.photographed())
        path.write_text(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if not line.startswith("![")
            ),
            encoding="utf-8",
        )

        (entry,) = repository.status()

        assert entry.status is Status.MODIFIED
        assert entry.changed_fields() == ["photo"]
        assert entry.has_local_changes()

    def test_the_hidden_bookkeeping_is_not_an_edit(self, repository):
        """A file cannot carry `photo_hash` and friends, so their absence on
        the parse side must never read as a change somebody made."""
        pull(repository, self.photographed(photo_hash="hash-1"))

        (entry,) = repository.status()

        assert entry.changed_fields() == []

    def test_swapped_bytes_read_as_a_modified_photo(self, repository):
        recipe = self.photographed()
        pull(repository, recipe)
        repository.write_photo(recipe.uid, "A-1.jpg", "hash-1", b"downloaded")

        (repository.attachments_dir / "A-1.jpg").write_bytes(b"the user's own")

        (entry,) = repository.status()
        assert entry.status is Status.MODIFIED
        assert entry.photo_replaced
        assert entry.changed_fields() == ["photo"]

    def test_untouched_bytes_do_not(self, repository):
        recipe = self.photographed()
        pull(repository, recipe)
        repository.write_photo(recipe.uid, "A-1.jpg", "hash-1", b"downloaded")

        (entry,) = repository.status()

        assert entry.status is Status.UNCHANGED
        assert not entry.photo_replaced

    def test_a_missing_attachment_is_not_a_replacement(self, repository):
        """Gone is `pull`'s to heal, not an edit to push."""
        recipe = self.photographed()
        pull(repository, recipe)
        repository.write_photo(recipe.uid, "A-1.jpg", "hash-1", b"downloaded")

        (repository.attachments_dir / "A-1.jpg").unlink()

        (entry,) = repository.status()
        assert entry.status is Status.UNCHANGED
        assert not entry.photo_replaced

    def test_the_hidden_bookkeeping_never_reaches_the_file(self, repository):
        path = pull(repository, self.photographed(photo_hash="secret-hash"))

        content = path.read_text(encoding="utf-8")

        assert "secret-hash" not in content
        assert "photo_url" not in content
