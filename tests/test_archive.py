import argparse
import gzip
import json
from base64 import b64decode, b64encode
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import pytest

from paprika_recipes.archive import (
    Archive,
    ArchiveRecipe,
    attach_photo,
    detach_photo,
    identify,
)
from paprika_recipes.commands import create_archive, extract_archive
from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.markdown import parse_recipe, render_recipe

#: A 1x1 transparent PNG -- the smallest real image to hand.
PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwACh"
    "wGA60e6kgAAAABJRU5ErkJggg=="
)
PNG_DATA = b64encode(PNG).decode("ascii")


def archive_bytes(*recipes: dict) -> bytes:
    """Build a .paprikarecipes file the way Paprika's own export does."""
    out = BytesIO()

    with ZipFile(out, mode="w") as zip_file:
        for index, recipe in enumerate(recipes):
            zip_file.writestr(
                f"{recipe['name']}-{index}.paprikarecipe",
                gzip.compress(json.dumps(recipe).encode("utf-8")),
            )

    return out.getvalue()


def entry(**overrides) -> dict:
    data: dict[str, Any] = {
        "name": "Khachapuri",
        "uid": "4C855813-25B8-41CD-96E7-5B38AA7AAAAF",
        "ingredients": "1 tsp salt\n2 cups flour",
        "directions": "Combine.\n\nBake.",
        "photo": None,
        "photo_data": None,
        "photos": [],
        "rating": 4,
    }
    data.update(overrides)

    return data


def run(module, **options) -> None:
    module.Command({}, argparse.Namespace(**options)).handle()


@pytest.fixture
def extract(tmp_path):
    def extract(*recipes: dict):
        archive = tmp_path / "export.paprikarecipes"
        archive.write_bytes(archive_bytes(*recipes))

        root = tmp_path / "recipes"
        run(extract_archive, archive_path=archive, export_path=root)

        return root

    return extract


def repack(root, archive_path):
    run(create_archive, export_path=root, archive_path=archive_path)

    with open(archive_path, "rb") as inf:
        return Archive.from_file(inf)


class TestRecipesSharingATitle:
    """Two recipes can have the same name; an archive names entries by it."""

    def test_are_read_back_as_two_different_recipes(self):
        """Opening entries by name would hand back the same one twice."""
        # Both entries deliberately share a name, as Paprika's own would.
        out = BytesIO()
        with ZipFile(out, mode="w") as zip_file:
            for uid, ingredients in (("FIRST", "salt"), ("SECOND", "pepper")):
                zip_file.writestr(
                    "Khachapuri.paprikarecipe",
                    gzip.compress(
                        json.dumps(entry(uid=uid, ingredients=ingredients)).encode()
                    ),
                )
        data = BytesIO(out.getvalue())

        recipes = list(Archive.from_file(data).recipes)

        assert [recipe.uid for recipe in recipes] == ["FIRST", "SECOND"]
        assert [recipe.ingredients for recipe in recipes] == ["salt", "pepper"]

    def test_are_written_as_distinguishable_entries(self, tmp_path):
        archive = Archive()
        archive.add_recipe(ArchiveRecipe(name="Khachapuri", uid="FIRST-1"))
        archive.add_recipe(ArchiveRecipe(name="Khachapuri", uid="SECOND-2"))

        path = tmp_path / "out.paprikarecipes"
        with open(path, "wb") as outf:
            archive.as_paprikarecipes(outf)

        with ZipFile(path) as zip_file:
            names = [info.filename for info in zip_file.infolist()]

        assert len(set(names)) == 2

    def test_survive_a_full_round_trip(self, tmp_path):
        archive = Archive()
        archive.add_recipe(ArchiveRecipe(name="Same", uid="FIRST-1", notes="one"))
        archive.add_recipe(ArchiveRecipe(name="Same", uid="SECOND-2", notes="two"))

        path = tmp_path / "out.paprikarecipes"
        with open(path, "wb") as outf:
            archive.as_paprikarecipes(outf)

        with open(path, "rb") as inf:
            recipes = list(Archive.from_file(inf).recipes)

        assert sorted(recipe.notes for recipe in recipes) == ["one", "two"]


class TestPhotos:
    def test_a_photo_is_written_beside_the_recipe(self, tmp_path):
        recipe = ArchiveRecipe(name="Test", photo_data=PNG_DATA)

        result = detach_photo(recipe, tmp_path / "Test.md")

        assert (tmp_path / "Test.png").read_bytes() == PNG
        assert result.photo == "Test.png"

    def test_the_photo_leaves_the_recipe_itself(self, tmp_path):
        """A megabyte of base64 in the frontmatter would be unreadable."""
        recipe = ArchiveRecipe(name="Test", photo_data=PNG_DATA)

        result = detach_photo(recipe, tmp_path / "Test.md")

        assert result.photo_data is None
        assert "iVBOR" not in render_recipe(result)

    def test_an_unrecognised_image_is_assumed_to_be_a_jpeg(self, tmp_path):
        recipe = ArchiveRecipe(
            name="Test", photo_data=b64encode(b"\xff\xd8\xff\xe0jpeg").decode("ascii")
        )

        assert detach_photo(recipe, tmp_path / "Test.md").photo == "Test.jpg"

    def test_a_recipe_without_a_photo_is_untouched(self, tmp_path):
        recipe = ArchiveRecipe(name="Test")

        assert detach_photo(recipe, tmp_path / "Test.md") is recipe
        assert list(tmp_path.iterdir()) == []

    def test_data_that_is_not_an_image_is_left_where_it_is(self, tmp_path):
        """Better an ugly file than a lost photo."""
        recipe = ArchiveRecipe(name="Test", photo_data="not base64 at all!!")

        result = detach_photo(recipe, tmp_path / "Test.md")

        assert result.photo_data == "not base64 at all!!"

    def test_a_photo_is_read_back_in(self, tmp_path):
        (tmp_path / "Test.png").write_bytes(PNG)
        recipe = ArchiveRecipe(name="Test", photo="Test.png")

        result = attach_photo(recipe, tmp_path / "Test.md")

        assert result.photo_data == PNG_DATA

    def test_a_missing_photo_is_not_an_error(self, tmp_path):
        recipe = ArchiveRecipe(name="Test", photo="Gone.png")

        assert attach_photo(recipe, tmp_path / "Test.md").photo_data is None

    def test_survives_the_whole_trip(self, tmp_path):
        path = tmp_path / "Test.md"

        detached = detach_photo(ArchiveRecipe(name="Test", photo_data=PNG_DATA), path)
        path.write_text(render_recipe(detached), encoding="utf-8")
        reloaded = attach_photo(
            parse_recipe(path.read_text(encoding="utf-8"), ArchiveRecipe), path
        )

        assert reloaded.photo_data == PNG_DATA


class TestExtracting:
    def test_writes_recipes_in_the_same_format_clone_writes(self, extract):
        content = (extract(entry()) / "Khachapuri.md").read_text(encoding="utf-8")

        assert content.startswith("---\n")
        assert "# Khachapuri" in content
        assert "## Ingredients" in content
        assert "- 1 tsp salt" in content

    def test_writes_nothing_else(self, extract):
        """The old `.paprikarecipe.yaml` format is gone."""
        assert [path.name for path in extract(entry()).iterdir()] == ["Khachapuri.md"]

    def test_disambiguates_recipes_sharing_a_name(self, extract):
        root = extract(entry(), entry(uid="OTHER-UID"))

        assert len(list(root.glob("*.md"))) == 2

    def test_writes_a_photo_beside_its_recipe(self, extract):
        root = extract(entry(photo_data=PNG_DATA))

        assert (root / "Khachapuri.png").read_bytes() == PNG
        assert "iVBOR" not in (root / "Khachapuri.md").read_text(encoding="utf-8")


class TestCreating:
    def test_round_trips_a_recipe_through_an_archive(self, tmp_path, extract):
        root = extract(entry(photo_data=PNG_DATA))

        (recipe,) = repack(root, tmp_path / "rebuilt.paprikarecipes").recipes

        assert recipe.name == "Khachapuri"
        assert recipe.ingredients == "1 tsp salt\n2 cups flour"
        assert recipe.directions == "Combine.\n\nBake."
        assert recipe.rating == 4
        assert recipe.photo_data == PNG_DATA

    def test_carries_an_edit_back_into_the_archive(self, tmp_path, extract):
        root = extract(entry())
        path = root / "Khachapuri.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("1 tsp salt", "2 tsp salt"),
            encoding="utf-8",
        )

        (recipe,) = repack(root, tmp_path / "rebuilt.paprikarecipes").recipes

        assert recipe.ingredients == "2 tsp salt\n2 cups flour"

    def test_finds_recipes_in_subdirectories(self, tmp_path, extract):
        root = extract(entry())
        (root / "Breads").mkdir()
        (root / "Khachapuri.md").rename(root / "Breads" / "Khachapuri.md")

        assert repack(root, tmp_path / "rebuilt.paprikarecipes").count() == 1

    def test_ignores_a_repositorys_bookkeeping(self, tmp_path, extract):
        """A cloned directory should pack too, without its base copies."""
        root = extract(entry())
        (root / ".paprika" / "recipes").mkdir(parents=True)
        (root / ".paprika" / "recipes" / "notes.md").write_text("hi", encoding="utf-8")

        assert repack(root, tmp_path / "rebuilt.paprikarecipes").count() == 1

    def test_refuses_a_directory_with_no_recipes(self, tmp_path):
        (tmp_path / "empty").mkdir()

        with pytest.raises(PaprikaUserError, match="No recipe files"):
            run(
                create_archive,
                export_path=tmp_path / "empty",
                archive_path=tmp_path / "out.paprikarecipes",
            )

    def test_blames_the_file_that_cannot_be_read(self, tmp_path, extract):
        root = extract(entry())
        (root / "Broken.md").write_text("no frontmatter here", encoding="utf-8")

        with pytest.raises(PaprikaUserError, match="Broken.md"):
            run(
                create_archive,
                export_path=root,
                archive_path=tmp_path / "out.paprikarecipes",
            )


class TestIdentifyingRecipesToPack:
    def test_gives_a_recipe_written_by_hand_a_uid(self):
        """Paprika tracks what it imports by uid, so an archive needs one."""
        identified = identify(ArchiveRecipe(name="Mine", uid=""))

        assert identified.uid

    def test_gives_two_of_them_different_uids(self):
        first = identify(ArchiveRecipe(name="Mine", uid=""))
        second = identify(ArchiveRecipe(name="Yours", uid=""))

        assert first.uid != second.uid

    def test_leaves_an_existing_uid_alone(self):
        identified = identify(ArchiveRecipe(name="Mine", uid="ABC"))

        assert identified.uid == "ABC"
