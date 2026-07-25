"""Rendering recipes to markdown files, and reading them back again.

Paprika's own model is almost entirely unstructured -- of the fields on
`BaseRecipe`, only `categories` and `rating` hold anything but a string, and
the interesting ones (`ingredients`, `directions`, `notes`) are opaque text
blobs.  We therefore make no attempt to impose structure the source data does
not have: prose fields are written out verbatim and read back verbatim.

In particular we deliberately do *not* follow RecipeMD's convention of pulling
ingredient amounts out into an italicised prefix.  Real recipes contain lines
like `185 g wet ingredients: 2 large eggs, 3 large egg yolks, and enough water
to reach 185 g in total.` -- there is no amount to extract, and guessing at one
would make the round-trip lossy for no gain.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, TypeVar

from yaml import YAMLError

from .exceptions import PaprikaUserError
from .utils import dump_yaml, load_yaml

if TYPE_CHECKING:
    from .recipe import BaseRecipe

T = TypeVar("T", bound="BaseRecipe")

FRONTMATTER_DELIMITER: Final = "---"

#: The document's title, and the level at which sections are delimited.
TITLE_PREFIX: Final = "# "
HEADING_PREFIX: Final = "## "

#: Written as the document's `# ` title rather than as a frontmatter field.
TITLE_FIELD: Final = "name"

#: Written directly beneath the title, with no heading of its own.
DESCRIPTION_FIELD: Final = "description"

#: Written as `## ` sections, in this order.  Every recipe field not named
#: here or above is written to the frontmatter instead.
SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("Ingredients", "ingredients"),
    ("Directions", "directions"),
    ("Notes", "notes"),
    ("Nutritional Information", "nutritional_info"),
)

#: Fields rendered as a markdown bullet list, one bullet per line of the blob.
LIST_FIELDS: Final = frozenset({"ingredients"})

#: Bullet characters we will accept when reading a list field back in.  We
#: only ever *write* `-`, but a human editing the file might reasonably type
#: any of these.
BULLETS: Final = ("- ", "* ", "+ ")

BODY_FIELDS: Final = frozenset(
    {TITLE_FIELD, DESCRIPTION_FIELD} | {field for _, field in SECTIONS}
)

_HEADINGS_BY_TITLE: Final = dict(SECTIONS)


@dataclass(frozen=True)
class ExtraSection:
    """A `## ` section of a recipe file that is not one of ours."""

    #: The recipe field whose section this one followed, so that it can be put
    #: back where its author left it.  Empty if it came before any of ours.
    anchor: str
    #: The section verbatim, its heading included.
    text: str


@dataclass(frozen=True)
class Extras:
    """The parts of a recipe file that belong to its reader, not to Paprika.

    A recipe file is meant to be a good citizen of whatever directory it lands
    in, and somewhere like an Obsidian vault that means the file is not
    exclusively ours: a user may add `tags:` to the frontmatter and a
    `## Substitutions` section of their own to the body.  Paprika has nowhere
    to put either, so we never send them anywhere -- but we do carry them
    through unchanged whenever we rewrite the file.
    """

    frontmatter: dict[str, Any] = field(default_factory=dict)
    sections: tuple[ExtraSection, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.frontmatter or self.sections)

    def describe(self) -> str:
        """Name what is here, briefly enough to sit at the end of a line.

        Whoever wrote this into their file should be told plainly that it is
        staying put rather than going to Paprika -- silently keeping it is
        only marginally better than silently dropping it, since either way
        they are left guessing what happened to it.
        """
        headings = [section.text.split("\n", 1)[0] for section in self.sections]
        keys = [f"{key}:" for key in sorted(self.frontmatter)]

        return ", ".join([*headings, *keys])


def render_recipe(recipe: BaseRecipe, extras: Extras | None = None) -> str:
    """Render a recipe as a markdown document with YAML frontmatter."""
    extras = extras if extras is not None else Extras()
    data = recipe.as_dict()

    frontmatter: dict[str, Any] = dict(extras.frontmatter)
    frontmatter.update(
        {key: value for key, value in data.items() if key not in BODY_FIELDS}
    )

    out = io.StringIO()
    out.write(f"{FRONTMATTER_DELIMITER}\n")
    dump_yaml(frontmatter, out)
    out.write(f"{FRONTMATTER_DELIMITER}\n\n")
    out.write(f"# {data.get(TITLE_FIELD, '')}\n")

    description = _render_field(DESCRIPTION_FIELD, data.get(DESCRIPTION_FIELD) or "")
    if description:
        out.write(f"\n{description}\n")

    placed = {""}
    _render_extras(out, extras, "")

    for title, field_name in SECTIONS:
        value = data.get(field_name) or ""
        if not value:
            continue

        out.write(f"\n## {title}\n\n")
        out.write(_render_field(field_name, value))
        out.write("\n")

        placed.add(field_name)
        _render_extras(out, extras, field_name)

    # A section anchored to one of ours that this recipe no longer has still
    # needs to go somewhere; the end is the only honest place left for it.
    for section in extras.sections:
        if section.anchor not in placed:
            out.write(f"\n{section.text}\n")

    return out.getvalue()


def parse_document(content: str, recipe_class: type[T]) -> tuple[T, Extras]:
    """Read a document as both a recipe and whatever else its file holds."""
    frontmatter, body = _split_frontmatter(content)
    fields, sections = _parse_body(body)
    known = {field.name for field in recipe_class.get_all_fields()}

    data: dict[str, Any] = dict(frontmatter)
    data.update(fields)

    return recipe_class.from_dict(data), Extras(
        frontmatter={
            key: value for key, value in frontmatter.items() if key not in known
        },
        sections=sections,
    )


def parse_recipe(content: str, recipe_class: type[T]) -> T:
    """Read the recipe out of a document produced by `render_recipe`."""
    return parse_document(content, recipe_class)[0]


def read_extras(content: str, recipe_class: type[BaseRecipe]) -> Extras:
    """Read the parts of a document that are not the recipe."""
    return parse_document(content, recipe_class)[1]


def documents_differ(content: str, rendered: str) -> bool:
    """Does a recipe file say something different from a rendering of a recipe?

    The two halves of the document are compared differently, on purpose.

    The body is compared as *text*.  Our markdown encoding of a recipe's prose
    is a bespoke transformation, and comparing the text is what keeps change
    detection independent of how faithfully that transformation round-trips:
    both sides pass through it identically, so any normalisation cancels out.

    The frontmatter is compared as *data*.  It is ordinary YAML, which we did
    not invent and which `safe_load` reads back faithfully -- and there are
    many ways to spell the same mapping.  A user who types `tags: [dinner]`
    into their editor rather than the block form we would have written has not
    edited the recipe, and should not be told they have.
    """
    try:
        theirs, their_body = _split_frontmatter(content)
    except PaprikaUserError:
        # Not a document we could have written; treat it as changed and let
        # whoever tries to read it produce the useful error message.
        return True

    ours, our_body = _split_frontmatter(rendered)

    return ours != theirs or our_body != their_body


def normalize_recipe(recipe: T) -> T:
    """Return a copy of `recipe` in the form our markdown can represent exactly.

    Markdown has nowhere to put trailing blank lines at the end of a section --
    the whitespace before the next heading is ours, not the recipe's -- so a
    field ending in a newline would come back a byte shorter than it went out.
    Rather than treat that as a failure, we flatten it on the way in, so that
    the base copy and the working file always agree about what the recipe says.

    This is the only normalisation we perform. It discards nothing a cook would
    notice, and it only ever reaches the server for a field the user edited
    anyway.
    """
    changes: dict[str, Any] = {}

    for field_name in BODY_FIELDS:
        value = getattr(recipe, field_name, None)

        if not isinstance(value, str):
            continue

        normalized = value.strip() if field_name == TITLE_FIELD else value.rstrip("\n")

        if normalized != value:
            changes[field_name] = normalized

    return replace(recipe, **changes) if changes else recipe


def find_lossy_fields(recipe: BaseRecipe, extras: Extras | None = None) -> list[str]:
    """Return the parts of a recipe that do not survive a render/parse round-trip.

    Under normal circumstances this is empty; it is non-empty when a recipe
    contains something our format cannot express unambiguously.  Callers can
    use it to refuse to write a file they would not be able to read back
    correctly.
    """
    rendered = render_recipe(recipe, extras)
    reparsed = parse_recipe(rendered, type(recipe))

    before = recipe.as_dict()
    after = reparsed.as_dict()

    lossy = sorted(key for key in before if before[key] != after.get(key))

    if extras is not None and read_extras(rendered, type(recipe)) != extras:
        lossy.append("the sections you added yourself")

    return lossy


def _render_field(field_name: str, value: str) -> str:
    if field_name not in LIST_FIELDS:
        return _escape_headings(value.rstrip("\n"))

    # Every line of a list field is prefixed with a bullet, which already
    # stops it being mistaken for one of our headings.
    return "\n".join(f"- {line}" if line else "" for line in value.split("\n"))


def _parse_field(field_name: str, value: str) -> str:
    if field_name not in LIST_FIELDS:
        return _unescape_headings(value)

    lines = []
    for line in value.split("\n"):
        for bullet in BULLETS:
            if line.startswith(bullet):
                line = line[len(bullet) :]
                break

        lines.append(line)

    return "\n".join(lines)


def _is_heading(line: str) -> bool:
    return line.startswith(HEADING_PREFIX)


def _escape_headings(value: str) -> str:
    """Stop prose from being mistaken for a section heading.

    Every `## ` line we write out of a recipe's prose is escaped, not just the
    ones that collide with our own section names.  That is what makes the
    format unambiguous in the other direction: an *unescaped* `## ` in a file
    is always a section boundary, so a section the user added themselves can
    be told apart from a line of directions that merely looks like one.

    Backslash-escaping the `#` is standard CommonMark and renders as a literal
    `#`, so the file still reads correctly to a human and to any previewer.
    """
    return "\n".join(
        f"\\{line}" if _is_heading(line) else line for line in value.split("\n")
    )


def _unescape_headings(value: str) -> str:
    return "\n".join(
        line[1:] if line.startswith(f"\\{HEADING_PREFIX}") else line
        for line in value.split("\n")
    )


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.split("\n")

    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise PaprikaUserError(
            "Recipe does not begin with a YAML frontmatter block; expected the "
            f"first line to be {FRONTMATTER_DELIMITER!r}."
        )

    remainder = lines[1:]

    for index, line in enumerate(remainder):
        if line.strip() != FRONTMATTER_DELIMITER:
            continue

        try:
            frontmatter = load_yaml("\n".join(remainder[:index])) or {}
        except YAMLError as e:
            raise PaprikaUserError(f"Recipe's YAML frontmatter could not be read: {e}")

        if not isinstance(frontmatter, dict):
            raise PaprikaUserError(
                "Recipe's YAML frontmatter should be a mapping of field names "
                f"to values, but found {type(frontmatter).__name__}."
            )

        return frontmatter, "\n".join(remainder[index + 1 :])

    raise PaprikaUserError(
        "Recipe's YAML frontmatter block was opened but never closed; "
        f"expected a line reading {FRONTMATTER_DELIMITER!r}."
    )


def _parse_body(body: str) -> tuple[dict[str, str], tuple[ExtraSection, ...]]:
    """Split a document body into the recipe's fields and everything else."""
    result: dict[str, str] = {}
    seen_title = False

    # Each block is a heading and the lines beneath it; the first block, with
    # no heading, is the description.
    blocks: list[tuple[str, list[str]]] = [("", [])]

    for line in body.split("\n"):
        if not seen_title and line.startswith(TITLE_PREFIX):
            result[TITLE_FIELD] = line[len(TITLE_PREFIX) :].strip()
            seen_title = True
            blocks = [("", [])]
            continue

        if _is_heading(line):
            blocks.append((line[len(HEADING_PREFIX) :].strip(), []))
            continue

        blocks[-1][1].append(line)

    extras: list[ExtraSection] = []
    anchor = ""

    for heading, lines in blocks:
        text = "\n".join(lines).strip("\n")

        if not heading:
            if text:
                result[DESCRIPTION_FIELD] = _parse_field(DESCRIPTION_FIELD, text)
            continue

        field_name = _HEADINGS_BY_TITLE.get(heading)

        if field_name is None:
            heading_line = f"{HEADING_PREFIX}{heading}"
            extras.append(
                ExtraSection(
                    anchor, f"{heading_line}\n\n{text}" if text else heading_line
                )
            )
            continue

        result[field_name] = _parse_field(field_name, text)
        anchor = field_name

    return result, tuple(extras)


def _render_extras(out: io.StringIO, extras: Extras, anchor: str) -> None:
    for section in extras.sections:
        if section.anchor == anchor:
            out.write(f"\n{section.text}\n")
