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
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final, TypeVar

from .exceptions import PaprikaUserError
from .utils import dump_yaml, load_yaml

if TYPE_CHECKING:
    from .recipe import BaseRecipe

T = TypeVar("T", bound="BaseRecipe")

FRONTMATTER_DELIMITER: Final = "---"

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


def render_recipe(recipe: BaseRecipe) -> str:
    """Render a recipe as a markdown document with YAML frontmatter."""
    data = recipe.as_dict()

    frontmatter = {key: value for key, value in data.items() if key not in BODY_FIELDS}

    out = io.StringIO()
    out.write(f"{FRONTMATTER_DELIMITER}\n")
    dump_yaml(frontmatter, out)
    out.write(f"{FRONTMATTER_DELIMITER}\n\n")
    out.write(f"# {data.get(TITLE_FIELD, '')}\n")

    description = _render_field(DESCRIPTION_FIELD, data.get(DESCRIPTION_FIELD) or "")
    if description:
        out.write(f"\n{description}\n")

    for title, field_name in SECTIONS:
        value = data.get(field_name) or ""
        if not value:
            continue

        out.write(f"\n## {title}\n\n")
        out.write(_render_field(field_name, value))
        out.write("\n")

    return out.getvalue()


def parse_recipe(content: str, recipe_class: type[T]) -> T:
    """Read back a document produced by `render_recipe`."""
    frontmatter, body = _split_frontmatter(content)

    data: dict[str, Any] = dict(frontmatter)
    data.update(_parse_body(body))

    return recipe_class.from_dict(data)


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


def find_lossy_fields(recipe: BaseRecipe) -> list[str]:
    """Return the fields that do not survive a render/parse round-trip.

    Under normal circumstances this is empty; it is non-empty when a recipe
    contains something our format cannot express unambiguously (a directions
    blob containing a line that looks like one of our own headings, say).
    Callers can use it to refuse to write a file they would not be able to
    read back correctly.
    """
    reparsed = parse_recipe(render_recipe(recipe), type(recipe))

    before = recipe.as_dict()
    after = reparsed.as_dict()

    return sorted(key for key in before if before[key] != after.get(key))


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


def _is_section_heading(line: str) -> bool:
    return line.startswith("## ") and line[3:].strip() in _HEADINGS_BY_TITLE


def _escape_headings(value: str) -> str:
    """Stop prose from being mistaken for one of our own section headings.

    A recipe whose directions happen to contain a line reading `## Notes` is
    unusual but perfectly legal, and we would otherwise read half its
    directions back as notes. Backslash-escaping the `#` is standard CommonMark
    and renders as a literal `#`, so the file still looks right to a human.
    """
    return "\n".join(
        f"\\{line}" if _is_section_heading(line) else line for line in value.split("\n")
    )


def _unescape_headings(value: str) -> str:
    return "\n".join(
        line[1:] if line.startswith("\\") and _is_section_heading(line[1:]) else line
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

        frontmatter = load_yaml("\n".join(remainder[:index])) or {}

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


def _parse_body(body: str) -> dict[str, str]:
    result: dict[str, str] = {}

    # `None` while we are accumulating the description -- that is, before we
    # have encountered any of our own `## ` headings.
    current: str | None = None
    buffer: list[str] = []
    seen_title = False

    def flush() -> None:
        text = "\n".join(buffer).strip("\n")

        if current is None:
            if text:
                result[DESCRIPTION_FIELD] = _parse_field(DESCRIPTION_FIELD, text)
        else:
            result[current] = _parse_field(current, text)

    for line in body.split("\n"):
        if not seen_title and line.startswith("# "):
            result[TITLE_FIELD] = line[2:].strip()
            seen_title = True
            buffer = []
            continue

        if line.startswith("## ") and line[3:].strip() in _HEADINGS_BY_TITLE:
            flush()
            current = _HEADINGS_BY_TITLE[line[3:].strip()]
            buffer = []
            continue

        buffer.append(line)

    flush()

    return result
