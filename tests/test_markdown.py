import pytest

from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.markdown import (
    DocumentFormat,
    Extras,
    ExtraSection,
    documents_differ,
    find_lossy_fields,
    foreign_uid_key,
    normalize_recipe,
    parse_recipe,
    read_extras,
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

    def test_escapes_every_heading_in_prose_not_just_our_own(self):
        """An unescaped `## ` must always mean a section boundary."""
        recipe = BaseRecipe(name="Test", directions="## Step One\n\nDo it.")

        assert "\\## Step One" in render_recipe(recipe)
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

        assert read_extras(content, BaseRecipe).frontmatter == {"tags": ["dinner"]}

    def test_reports_nothing_for_a_file_we_wrote_ourselves(self):
        content = render_recipe(BaseRecipe(name="Test", rating=4))

        assert not read_extras(content, BaseRecipe)

    def test_renders_extra_keys_back_into_the_frontmatter(self):
        extras = Extras(frontmatter={"tags": ["dinner"]})

        rendered = render_recipe(BaseRecipe(name="Test"), extras)

        assert "tags:" in rendered.split("---")[1]
        assert read_extras(rendered, BaseRecipe) == extras

    def test_ignores_extra_keys_when_parsing_the_recipe(self):
        recipe = BaseRecipe(name="Test", rating=4)

        rendered = render_recipe(recipe, Extras(frontmatter={"tags": ["dinner"]}))

        assert parse_recipe(rendered, BaseRecipe) == recipe

    def test_never_lets_extra_keys_shadow_a_recipe_field(self):
        rendered = render_recipe(
            BaseRecipe(name="Test", rating=4), Extras(frontmatter={"rating": 1})
        )

        assert parse_recipe(rendered, BaseRecipe).rating == 4


class TestExtraSections:
    """A `## ` section the user added that means nothing to Paprika."""

    def content(self, *, before_directions: bool = True) -> str:
        own = "## My Own Notes\n\nI keep my own stuff here.\n\n"
        directions = "## Directions\n\nBake it.\n"

        return (
            "---\nuid: ABC\n---\n\n# Khachapuri\n\n"
            "## Ingredients\n\n- 1 tsp salt\n\n"
            + (own + directions if before_directions else directions + "\n" + own)
        )

    def test_is_not_swallowed_into_the_preceding_recipe_field(self):
        """The whole point: this used to end up inside `ingredients`."""
        recipe = parse_recipe(self.content(), BaseRecipe)

        assert recipe.ingredients == "1 tsp salt"
        assert recipe.directions == "Bake it."
        assert "My Own Notes" not in str(recipe.as_dict())

    def test_is_reported_as_the_users_own(self):
        extras = read_extras(self.content(), BaseRecipe)

        assert extras.sections == (
            ExtraSection("ingredients", "## My Own Notes\n\nI keep my own stuff here."),
        )

    def test_is_written_back_where_its_author_left_it(self):
        content = self.content()
        recipe = parse_recipe(content, BaseRecipe)

        rendered = render_recipe(recipe, read_extras(content, BaseRecipe))

        assert rendered.index("## My Own Notes") > rendered.index("## Ingredients")
        assert rendered.index("## My Own Notes") < rendered.index("## Directions")

    def test_survives_a_round_trip_unchanged(self):
        content = self.content()
        extras = read_extras(content, BaseRecipe)
        rendered = render_recipe(parse_recipe(content, BaseRecipe), extras)

        assert read_extras(rendered, BaseRecipe) == extras
        assert find_lossy_fields(parse_recipe(content, BaseRecipe), extras) == []

    def test_keeps_a_trailing_section_at_the_end(self):
        content = self.content(before_directions=False)
        extras = read_extras(content, BaseRecipe)

        assert extras.sections[0].anchor == "directions"

        rendered = render_recipe(parse_recipe(content, BaseRecipe), extras)

        assert rendered.index("## My Own Notes") > rendered.index("## Directions")

    def test_keeps_a_section_that_came_before_any_of_ours(self):
        content = (
            "---\nuid: ABC\n---\n\n# Khachapuri\n\n"
            "## Shopping\n\nGo to the shop.\n\n"
            "## Ingredients\n\n- 1 tsp salt\n"
        )
        extras = read_extras(content, BaseRecipe)

        assert extras.sections[0].anchor == ""

        rendered = render_recipe(parse_recipe(content, BaseRecipe), extras)

        assert rendered.index("## Shopping") < rendered.index("## Ingredients")

    def test_falls_back_to_the_end_when_its_anchor_is_gone(self):
        """The recipe may lose the section the extra was sitting under."""
        extras = Extras(sections=(ExtraSection("notes", "## Mine\n\nStuff."),))

        rendered = render_recipe(BaseRecipe(name="Test", notes=""), extras)

        assert read_extras(rendered, BaseRecipe) == Extras(
            sections=(ExtraSection("", "## Mine\n\nStuff."),)
        )

    def test_an_empty_section_is_still_kept(self):
        content = "---\nuid: ABC\n---\n\n# Test\n\n## Mine\n"

        assert read_extras(content, BaseRecipe).sections == (
            ExtraSection("", "## Mine"),
        )


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


class TestReadingAUid:
    def test_leaves_a_recipe_without_one_empty(self):
        recipe = parse_recipe("---\ntags:\n- dinner\n---\n\n# Mine\n", BaseRecipe)

        assert recipe.uid == ""

    def test_reads_the_one_that_is_there(self):
        recipe = parse_recipe("---\nuid: ABC\n---\n\n# Mine\n", BaseRecipe)

        assert recipe.uid == "ABC"


class TestSpottingAForeignUid:
    @pytest.mark.parametrize(
        "key", ["uid", "paprika_uid", "paprika-uid", "Paprika_UID"]
    )
    def test_recognises_a_uid_by_another_name(self, key):
        assert foreign_uid_key(Extras(frontmatter={key: "ABC"})) == key

    @pytest.mark.parametrize("key", ["uuid", "guid", "tags", "aliases", "id"])
    def test_leaves_somebody_elses_field_alone(self, key):
        assert foreign_uid_key(Extras(frontmatter={key: "ABC"})) == ""

    def test_says_nothing_about_an_empty_file(self):
        assert foreign_uid_key(Extras()) == ""


class TestAFrontmatterPrefix:
    format = DocumentFormat("paprika_")

    def recipe(self, **overrides) -> BaseRecipe:
        data: dict = {"name": "Khachapuri", "uid": "ABC", "rating": 4}
        data.update(overrides)

        return BaseRecipe(**data)

    def test_prefixes_the_fields_it_writes(self):
        rendered = self.format.render(self.recipe())

        assert "paprika_rating: 4" in rendered
        assert "paprika_uid: ABC" in rendered

    def test_leaves_the_body_alone(self):
        """Only frontmatter can collide; the title and sections are ours."""
        rendered = self.format.render(self.recipe(ingredients="1 tsp salt"))

        assert "# Khachapuri" in rendered
        assert "## Ingredients" in rendered

    def test_reads_back_what_it_wrote(self):
        recipe = self.recipe(ingredients="1 tsp salt")

        parsed = self.format.parse_recipe(self.format.render(recipe), BaseRecipe)

        assert parsed.rating == 4
        assert parsed.uid == "ABC"
        assert parsed.ingredients == "1 tsp salt"

    def test_treats_an_unprefixed_field_as_the_users_own(self):
        """The entire point: a vault's `rating:` is not the recipe's rating."""
        recipe, extras = self.format.parse(
            "---\nrating: 1\npaprika_rating: 4\n---\n\n# Khachapuri\n", BaseRecipe
        )

        assert recipe.rating == 4
        assert extras.frontmatter == {"rating": 1}

    def test_never_reads_an_unprefixed_field_as_a_recipes(self):
        recipe, extras = self.format.parse(
            "---\nrating: 1\nsource: my brain\n---\n\n# Khachapuri\n", BaseRecipe
        )

        assert recipe.rating == 0
        assert recipe.source == ""
        assert extras.frontmatter == {"rating": 1, "source": "my brain"}

    def test_keeps_a_prefixed_field_it_does_not_know(self):
        """A file from a later version should lose nothing to an earlier one."""
        _, extras = self.format.parse(
            "---\npaprika_bogus: 1\n---\n\n# Khachapuri\n", BaseRecipe
        )

        assert extras.frontmatter == {"paprika_bogus": 1}

    def test_carries_the_users_frontmatter_through(self):
        rendered = self.format.render(
            self.recipe(), Extras(frontmatter={"tags": ["dinner"]})
        )

        assert "tags:" in rendered
        assert self.format.read_extras(rendered, BaseRecipe).frontmatter == {
            "tags": ["dinner"]
        }

    def test_an_unprefixed_file_reads_as_having_no_uid(self):
        """Which is what makes a mismatched prefix detectable rather than silent."""
        recipe, extras = self.format.parse(
            "---\nuid: ABC\n---\n\n# Khachapuri\n", BaseRecipe
        )

        assert recipe.uid == ""
        assert foreign_uid_key(extras) == "uid"


class TestNoPrefixAtAll:
    def test_is_what_the_default_format_does(self):
        assert DocumentFormat().frontmatter_prefix == ""

    def test_reads_exactly_as_before(self):
        recipe, extras = DocumentFormat().parse(
            "---\nrating: 4\ntags: [dinner]\n---\n\n# Khachapuri\n", BaseRecipe
        )

        assert recipe.rating == 4
        assert extras.frontmatter == {"tags": ["dinner"]}
