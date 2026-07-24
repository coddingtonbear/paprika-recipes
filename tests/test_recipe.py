import io

from paprika_recipes.archive import Archive, ArchiveRecipe
from paprika_recipes.recipe import BaseRecipe
from paprika_recipes.remote import RemoteRecipe


class TestFromDict:
    def test_ignores_unknown_fields(self):
        recipe = ArchiveRecipe.from_dict(
            {"name": "Tea", "in_trash": False, "not_a_real_field": 1}
        )

        assert recipe.name == "Tea"

    def test_populates_known_fields(self):
        recipe = RemoteRecipe.from_dict(
            {"name": "Tea", "ingredients": "1 bag tea", "in_trash": True}
        )

        assert recipe.ingredients == "1 bag tea"
        assert recipe.in_trash is True


class TestSafeName:
    def test_escapes_slashes(self):
        recipe = BaseRecipe(name="Lemon/Garlic Shrimp")

        assert "/" not in recipe.safe_name

    def test_preserves_unicode(self):
        recipe = BaseRecipe(name="Bánh Mì ½")

        assert recipe.safe_name == "Bánh Mì ½"


class TestArchiveRoundTrip:
    def test_recipe_survives_archive_round_trip(self):
        recipe = ArchiveRecipe(
            name="Bánh Mì ½",
            ingredients="1 baguette\n100g pâté",
            directions="Assemble.",
        )
        archive = Archive()
        archive.add_recipe(recipe)

        buffer = io.BytesIO()
        archive.as_paprikarecipes(buffer)
        buffer.seek(0)

        restored = list(Archive.from_file(buffer))
        assert len(restored) == 1
        assert restored[0] == recipe


class TestHash:
    def test_update_hash_is_stable(self):
        recipe = BaseRecipe(name="Tea")
        recipe.update_hash()
        first = recipe.hash

        recipe.update_hash()
        assert recipe.hash == first

    def test_update_hash_changes_with_content(self):
        recipe = BaseRecipe(name="Tea")
        recipe.update_hash()
        first = recipe.hash

        recipe.name = "Coffee"
        recipe.update_hash()
        assert recipe.hash != first
