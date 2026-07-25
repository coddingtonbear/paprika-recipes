import pytest

from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.markdown import (
    documents_differ,
    extra_frontmatter,
    find_lossy_fields,
    normalize_recipe,
    parse_recipe,
    render_recipe,
)
from paprika_recipes.recipe import BaseRecipe
from paprika_recipes.remote import RemoteRecipe


def roundtrip(recipe):
    return parse_recipe(render_recipe(recipe), type(recipe))


class TestRendering:
    def test_writes_the_name_as_the_title(self):
        rendered = render_recipe(BaseRecipe(name="Khachapuri"))

        assert "\n# Khachapuri\n" in rendered

    def test_writes_prose_fields_to_the_body_not_the_frontmatter(self):
        rendered = render_recipe(
            BaseRecipe(name="Cookies", ingredients="2 eggs", directions="Bake them.")
        )
        frontmatter = rendered.split("---")[1]

        assert "ingredients" not in frontmatter
        assert "directions" not in frontmatter

    def test_writes_structured_fields_to_the_frontmatter(self):
        rendered = render_recipe(
            BaseRecipe(name="Cookies", rating=4, categories=["Dessert"])
        )
        frontmatter = rendered.split("---")[1]

        assert "rating: 4" in frontmatter
        assert "Dessert" in frontmatter

    def test_writes_ingredients_as_a_bullet_list(self):
        rendered = render_recipe(BaseRecipe(ingredients="2 eggs\n1 cup flour"))

        assert "- 2 eggs\n- 1 cup flour" in rendered

    def test_omits_sections_with_no_content(self):
        rendered = render_recipe(BaseRecipe(name="Cookies", ingredients="2 eggs"))

        assert "## Ingredients" in rendered
        assert "## Notes" not in rendered
        assert "## Directions" not in rendered


class TestRoundTrip:
    def test_preserves_every_field(self):
        recipe = RemoteRecipe(
            name="Khachapuri",
            description="A Georgian cheese bread.",
            ingredients="1 tsp salt\n3 1/2 cup all-purpose flour",
            directions="Combine.\n\nBake.",
            notes="Best warm.",
            nutritional_info="Calories: 458kcal | Protein: 23g",
            categories=["Bread", "Georgian"],
            rating=4,
            difficulty="Medium",
            prep_time="2 hours",
            cook_time="20 minutes",
            total_time="2 hours 20 minutes",
            servings="Servings 8",
            source="Simplyhomecooked.com",
            source_url="https://simplyhomecooked.com/wprm_print/11091",
            uid="4C855813-25B8-41CD-96E7-5B38AA7AAAAF",
            in_trash=False,
            on_favorites=True,
        )

        assert find_lossy_fields(recipe) == []
        assert roundtrip(recipe).as_dict() == recipe.as_dict()

    @pytest.mark.parametrize(
        "ingredients",
        [
            # Group headers live inside the blob, undistinguished from
            # ingredients -- Paprika has no concept of a group.
            "For the dough:\n1 tsp salt\nFor the filling:\n4 eggs",
            # Real lines from the author's own account that would not survive
            # any attempt to parse amounts out of them.
            '300 g  "00" pasta flour or all-purpose flour',
            "185 g wet ingredients: 2 large eggs, 3 large egg yolks, and "
            "enough water to reach 185 g in total.",
            "4 eggs + 1 for egg wash",
            # A line that already looks like a bullet must not lose its dash.
            "- 1 cup water",
            "* 1 cup water",
            # Blank lines within the blob.
            "2 eggs\n\n1 cup flour",
        ],
    )
    def test_preserves_awkward_ingredient_blobs(self, ingredients):
        recipe = BaseRecipe(name="Test", ingredients=ingredients)

        assert roundtrip(recipe).ingredients == ingredients

    @pytest.mark.parametrize(
        "directions",
        [
            "Paragraph one.\n\nParagraph two.",
            # Paprika stores markdown inside directions already.
            "Roll out as shown in the [video](https://youtu.be/x?a=1&b=2).",
            "Mix 1/2 cup sugar & 3 eggs -- then bake at 350 degrees.",
            "1. Do this\n2. Then this",
        ],
    )
    def test_preserves_awkward_directions(self, directions):
        recipe = BaseRecipe(name="Test", directions=directions)

        assert roundtrip(recipe).directions == directions

    def test_preserves_unicode(self):
        recipe = BaseRecipe(name="Bánh Mì ½", ingredients="½ cup crème fraîche")

        result = roundtrip(recipe)

        assert result.name == "Bánh Mì ½"
        assert result.ingredients == "½ cup crème fraîche"

    def test_preserves_an_empty_recipe(self):
        recipe = BaseRecipe()

        assert find_lossy_fields(recipe) == []

    def test_accepts_alternate_bullet_characters(self):
        """A human editing the file might not use the dashes we write."""
        recipe = BaseRecipe(name="Test", ingredients="2 eggs")
        rendered = render_recipe(recipe).replace("- 2 eggs", "* 2 eggs")

        assert parse_recipe(rendered, BaseRecipe).ingredients == "2 eggs"


class TestHeadingCollisions:
    """Prose containing a line that looks like one of our section headings."""

    @pytest.mark.parametrize("heading", ["## Notes", "## Ingredients", "## Directions"])
    def test_survives_a_heading_inside_directions(self, heading):
        directions = f"Mix well.\n\n{heading}\n\nThis heading is not ours."
        recipe = BaseRecipe(name="Test", directions=directions)

        assert find_lossy_fields(recipe) == []
        assert roundtrip(recipe).directions == directions
        assert roundtrip(recipe).notes == ""

    def test_survives_a_heading_inside_the_description(self):
        recipe = BaseRecipe(name="Test", description="## Notes\n\nNot a section.")

        assert roundtrip(recipe).description == "## Notes\n\nNot a section."

    def test_escapes_the_heading_rather_than_dropping_it(self):
        recipe = BaseRecipe(name="Test", directions="## Notes")

        assert "\\## Notes" in render_recipe(recipe)

    def test_leaves_headings_that_are_not_ours_alone(self):
        recipe = BaseRecipe(name="Test", directions="## Step One\n\nDo it.")

        assert "\\##" not in render_recipe(recipe)
        assert roundtrip(recipe).directions == "## Step One\n\nDo it."


class TestNormalization:
    """Trailing newlines are the one thing markdown cannot hold onto."""

    def test_strips_trailing_newlines_from_prose_fields(self):
        recipe = BaseRecipe(
            description="A bread.\n",
            ingredients="1 tsp salt\n",
            directions="Bake.\n\n",
            notes="Best warm.\n",
            nutritional_info="Calories: 458kcal\n",
        )

        result = normalize_recipe(recipe)

        assert result.description == "A bread."
        assert result.ingredients == "1 tsp salt"
        assert result.directions == "Bake."
        assert result.notes == "Best warm."
        assert result.nutritional_info == "Calories: 458kcal"

    def test_strips_surrounding_whitespace_from_the_name(self):
        assert normalize_recipe(BaseRecipe(name="  Khachapuri  ")).name == "Khachapuri"

    def test_leaves_interior_blank_lines_alone(self):
        recipe = BaseRecipe(directions="One.\n\nTwo.\n")

        assert normalize_recipe(recipe).directions == "One.\n\nTwo."

    def test_leaves_frontmatter_fields_alone(self):
        recipe = BaseRecipe(source="Somewhere\n", uid="abc\n")

        result = normalize_recipe(recipe)

        assert result.source == "Somewhere\n"
        assert result.uid == "abc\n"

    def test_returns_the_same_object_when_nothing_needs_changing(self):
        recipe = BaseRecipe(name="Khachapuri", directions="Bake.")

        assert normalize_recipe(recipe) is recipe

    def test_makes_a_lossy_recipe_lossless(self):
        recipe = BaseRecipe(name="Test", directions="Bake.\n")

        assert find_lossy_fields(recipe) == ["directions"]
        assert find_lossy_fields(normalize_recipe(recipe)) == []

    def test_is_idempotent(self):
        recipe = normalize_recipe(BaseRecipe(name="Test ", directions="Bake.\n\n"))

        assert normalize_recipe(recipe) == recipe


class TestExtraFrontmatter:
    """Frontmatter that belongs to the user rather than to us."""

    def test_reports_only_the_keys_that_are_not_recipe_fields(self):
        content = render_recipe(BaseRecipe(name="Test")).replace(
            "---\n", "---\ntags: [dinner]\n", 1
        )

        assert extra_frontmatter(content, BaseRecipe) == {"tags": ["dinner"]}

    def test_reports_nothing_for_a_file_we_wrote_ourselves(self):
        content = render_recipe(BaseRecipe(name="Test", rating=4))

        assert extra_frontmatter(content, BaseRecipe) == {}

    def test_renders_extra_keys_back_into_the_frontmatter(self):
        rendered = render_recipe(BaseRecipe(name="Test"), {"tags": ["dinner"]})

        assert "tags:" in rendered.split("---")[1]
        assert extra_frontmatter(rendered, BaseRecipe) == {"tags": ["dinner"]}

    def test_ignores_extra_keys_when_parsing_the_recipe(self):
        recipe = BaseRecipe(name="Test", rating=4)

        rendered = render_recipe(recipe, {"tags": ["dinner"]})

        assert parse_recipe(rendered, BaseRecipe) == recipe

    def test_never_lets_extra_keys_shadow_a_recipe_field(self):
        rendered = render_recipe(BaseRecipe(name="Test", rating=4), {"rating": 1})

        assert parse_recipe(rendered, BaseRecipe).rating == 4


class TestDocumentComparison:
    """Frontmatter is compared as data; the body as text."""

    def test_a_file_matches_its_own_rendering(self):
        rendered = render_recipe(BaseRecipe(name="Test", directions="Bake."))

        assert not documents_differ(rendered, rendered)

    def test_reflowed_frontmatter_is_not_a_difference(self):
        recipe = BaseRecipe(name="Test", categories=["Bread", "Georgian"])
        rendered = render_recipe(recipe)
        reflowed = rendered.replace(
            "categories:\n- Bread\n- Georgian\n", "categories: [Bread, Georgian]\n"
        )

        assert reflowed != rendered
        assert not documents_differ(reflowed, rendered)

    def test_an_edited_frontmatter_value_is_a_difference(self):
        rendered = render_recipe(BaseRecipe(name="Test", rating=0))

        assert documents_differ(rendered.replace("rating: 0", "rating: 5"), rendered)

    def test_the_body_is_compared_as_text(self):
        """Reformatting prose counts, even where markdown would render alike."""
        rendered = render_recipe(BaseRecipe(name="Test", ingredients="2 eggs"))

        assert documents_differ(rendered.replace("- 2 eggs", "* 2 eggs"), rendered)

    def test_an_unreadable_file_counts_as_different(self):
        rendered = render_recipe(BaseRecipe(name="Test"))

        assert documents_differ("no frontmatter here", rendered)


class TestLossDetection:
    def test_reports_nothing_for_an_ordinary_recipe(self):
        recipe = BaseRecipe(
            name="Test", ingredients="2 eggs", directions="Bake.", notes="Tasty."
        )

        assert find_lossy_fields(recipe) == []


class TestParsingErrors:
    def test_rejects_a_document_with_no_frontmatter(self):
        with pytest.raises(PaprikaUserError, match="frontmatter"):
            parse_recipe("# Just A Title\n", BaseRecipe)

    def test_rejects_unterminated_frontmatter(self):
        with pytest.raises(PaprikaUserError, match="never closed"):
            parse_recipe("---\nuid: abc\n\n# Title\n", BaseRecipe)

    def test_rejects_frontmatter_that_is_not_a_mapping(self):
        with pytest.raises(PaprikaUserError, match="mapping"):
            parse_recipe("---\n- one\n- two\n---\n\n# Title\n", BaseRecipe)

    def test_rejects_frontmatter_that_is_not_valid_yaml(self):
        with pytest.raises(PaprikaUserError, match="could not be read"):
            parse_recipe("---\nname: [oops\n---\n\n# Title\n", BaseRecipe)

    def test_ignores_unknown_frontmatter_fields(self):
        """Users may keep their own metadata alongside ours."""
        content = "---\nuid: abc\nmy_own_field: hello\n---\n\n# Title\n"

        result = parse_recipe(content, BaseRecipe)

        assert result.uid == "abc"
        assert result.name == "Title"
