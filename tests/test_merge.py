from typing import Any

import pytest

from paprika_recipes.merge import (
    has_conflict_markers,
    merge_lines,
    merge_recipes,
    merge_text,
)
from paprika_recipes.recipe import BaseRecipe


def lines(text: str) -> list[str]:
    return text.split("\n")


class TestMergingLines:
    def test_leaves_untouched_text_alone(self):
        base = lines("one\ntwo\nthree")

        assert merge_lines(base, base, base) == (base, 0)

    def test_takes_an_edit_only_one_side_made(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree"),
            lines("one\ntwo\nthree"),
            lines("one\nTWO\nthree"),
        )

        assert merged == lines("one\nTWO\nthree")
        assert conflicts == 0

    def test_takes_edits_from_both_sides_when_they_do_not_overlap(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree"),
            lines("ONE\ntwo\nthree"),
            lines("one\ntwo\nTHREE"),
        )

        assert merged == lines("ONE\ntwo\nTHREE")
        assert conflicts == 0

    def test_takes_the_same_edit_once(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo"), lines("one\nTWO"), lines("one\nTWO")
        )

        assert merged == lines("one\nTWO")
        assert conflicts == 0

    def test_keeps_an_insertion_from_each_side(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo"),
            lines("zero\none\ntwo"),
            lines("one\ntwo\nthree"),
        )

        assert merged == lines("zero\none\ntwo\nthree")
        assert conflicts == 0

    def test_keeps_a_deletion_from_one_side(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree"), lines("one\nthree"), lines("one\ntwo\nthree")
        )

        assert merged == lines("one\nthree")
        assert conflicts == 0

    def test_marks_the_same_line_changed_differently(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree"),
            lines("one\nMINE\nthree"),
            lines("one\nTHEIRS\nthree"),
        )

        assert conflicts == 1
        assert merged == lines(
            "one\n<<<<<<< yours\nMINE\n=======\nTHEIRS\n>>>>>>> paprika\nthree"
        )

    def test_conflicts_only_where_the_edits_actually_overlap(self):
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree\nfour\nfive"),
            lines("ONE\ntwo\nMINE\nfour\nfive"),
            lines("one\ntwo\nTHEIRS\nfour\nFIVE"),
        )

        assert conflicts == 1
        # The edits either side of the disputed line came through cleanly.
        assert merged[0] == "ONE"
        assert merged[-1] == "FIVE"

    def test_a_conflict_covers_the_whole_hunk_that_overlaps(self):
        """Adjacent changed lines are one hunk, so one of them conflicting
        drags the rest of that hunk into the conflict -- as diff3 does."""
        merged, conflicts = merge_lines(
            lines("one\ntwo\nthree\nfour"),
            lines("one\ntwo\nMINE\nfour"),
            lines("one\ntwo\nTHEIRS\nFOUR"),
        )

        assert conflicts == 1
        assert merged[-1] == ">>>>>>> paprika"
        assert "FOUR" in merged

    def test_merges_into_empty_text(self):
        merged, conflicts = merge_lines([""], lines("mine"), [""])

        assert merged == lines("mine")
        assert conflicts == 0


class TestMergingText:
    def test_merges_an_ingredient_list(self):
        merged, conflicts = merge_text(
            "1 tsp salt\n2 cups flour",
            "1 tsp salt\n2 cups flour\n1 egg",
            "2 tsp salt\n2 cups flour",
        )

        assert merged == "2 tsp salt\n2 cups flour\n1 egg"
        assert conflicts == 0


class TestMergingRecipes:
    def base(self, **overrides) -> BaseRecipe:
        data: dict[str, Any] = {
            "name": "Khachapuri",
            "ingredients": "1 tsp salt\n2 cups flour",
            "directions": "Combine.\n\nBake.",
            "rating": 3,
        }
        data.update(overrides)

        return BaseRecipe(**data)

    def test_combines_edits_to_different_fields(self):
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(ingredients="2 tsp salt\n2 cups flour", uid=base.uid),
            self.base(notes="Best warm.", uid=base.uid),
        )

        assert merge.clean
        assert merge.recipe.ingredients == "2 tsp salt\n2 cups flour"
        assert merge.recipe.notes == "Best warm."

    def test_combines_edits_within_one_field(self):
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(ingredients="2 tsp salt\n2 cups flour", uid=base.uid),
            self.base(ingredients="1 tsp salt\n3 cups flour", uid=base.uid),
        )

        assert merge.clean
        assert merge.recipe.ingredients == "2 tsp salt\n3 cups flour"

    def test_reports_a_conflict_within_a_field(self):
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(directions="Mine.", uid=base.uid),
            self.base(directions="Theirs.", uid=base.uid),
        )

        assert merge.merged
        assert not merge.clean
        assert merge.conflicted == ("directions",)
        assert "<<<<<<< yours" in merge.recipe.directions

    def test_refuses_a_recipe_whose_rating_moved_on_both_sides(self):
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(rating=5, uid=base.uid),
            self.base(rating=1, uid=base.uid),
        )

        assert not merge.merged
        assert merge.unmergeable == ("rating",)

    def test_refuses_a_recipe_renamed_on_both_sides(self):
        """A conflict marker in a title would be worse than being asked."""
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(name="Mine", uid=base.uid),
            self.base(name="Theirs", uid=base.uid),
        )

        assert not merge.merged
        assert merge.unmergeable == ("name",)

    def test_accepts_a_rename_from_one_side_only(self):
        base = self.base()

        merge = merge_recipes(
            base,
            self.base(name="Renamed", uid=base.uid),
            self.base(notes="Theirs.", uid=base.uid),
        )

        assert merge.clean
        assert merge.recipe.name == "Renamed"
        assert merge.recipe.notes == "Theirs."

    def test_ignores_the_servers_hash(self):
        base = self.base(hash="aaa")

        merge = merge_recipes(
            base,
            self.base(hash="bbb", uid=base.uid),
            self.base(hash="ccc", uid=base.uid),
        )

        assert merge.clean

    def test_keeps_the_servers_identity(self):
        """The merge is built on the server's copy, so its hash comes along."""
        base = self.base(hash="aaa")
        remote = self.base(hash="ccc", notes="Theirs.", uid=base.uid)

        merge = merge_recipes(base, self.base(hash="bbb", uid=base.uid), remote)

        assert merge.recipe.hash == "ccc"


class TestDetectingMarkers:
    @pytest.mark.parametrize(
        "directions",
        [
            "<<<<<<< yours\nMine.\n=======\nTheirs.\n>>>>>>> paprika",
            "Bake.\n\n>>>>>>> paprika",
        ],
    )
    def test_finds_an_unresolved_merge(self, directions):
        assert has_conflict_markers(BaseRecipe(directions=directions))

    def test_ignores_an_ordinary_recipe(self):
        recipe = BaseRecipe(directions="Combine.\n\nBake.", notes="Best warm.")

        assert not has_conflict_markers(recipe)

    def test_ignores_a_marker_that_is_not_at_the_start_of_a_line(self):
        recipe = BaseRecipe(directions="Reduce until <<<<<<< thickened.")

        assert not has_conflict_markers(recipe)
