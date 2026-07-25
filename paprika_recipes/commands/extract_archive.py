import argparse
from pathlib import Path

from rich.progress import track

from ..archive import Archive, detach_photo
from ..command import BaseCommand
from ..exceptions import PaprikaUserError
from ..markdown import find_lossy_fields, normalize_recipe, render_recipe
from ..repository import unique_path
from ..types import ConfigDict


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Extracts a .paprikarecipes archive to a directory."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("archive_path", type=Path)
        parser.add_argument("export_path", type=Path)

    def handle(self) -> None:
        with open(self.options.archive_path, "rb") as inf:
            archive = Archive.from_file(inf)

        root: Path = self.options.export_path
        root.mkdir(parents=True, exist_ok=True)

        taken: set[Path] = set()

        for recipe in track(list(archive), description="Extracting recipes"):
            recipe = normalize_recipe(recipe)
            path = unique_path(root, recipe, taken)
            taken.add(path.resolve())

            # The photo goes beside the recipe rather than inside it; see
            # `archive.detach_photo`.
            recipe = detach_photo(recipe, path)

            lossy = find_lossy_fields(recipe)
            if lossy:
                raise PaprikaUserError(
                    f"Refusing to write {recipe.name!r}: {', '.join(lossy)} "
                    "could not be read back from the markdown we would have "
                    "written. Please report this as a bug."
                )

            with open(path, "w", encoding="utf-8") as outf:
                outf.write(render_recipe(recipe))
