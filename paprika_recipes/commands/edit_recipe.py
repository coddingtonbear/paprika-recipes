import argparse
import os
from typing import List

import enquiries
from rich.progress import track

from ..command import RemoteCommand
from ..exceptions import PaprikaUserError
from ..remote import RemoteRecipe
from ..types import ConfigDict
from ..utils import edit_recipe_interactively


class Command(RemoteCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Opens an editor allowing you to edit an existing paprika recipe."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser, config: ConfigDict) -> None:
        parser.add_argument("--editor", default=os.environ.get("EDITOR", "vim"))
        parser.add_argument("search_terms", nargs="*", type=str)

    def handle(self) -> None:
        remote = self.get_remote()

        recipes: List[RemoteRecipe] = []
        for recipe in track(
            remote, total=remote.count(), description="Loading Recipes"
        ):
            matched = True

            for term in self.options.search_terms:
                if term.lower() not in recipe.name.lower():
                    matched = False
                    break

            if matched:
                recipes.append(recipe)

        try:
            if len(recipes) > 1:
                choice = enquiries.choose(
                    "Select a recipe to edit", [recipe.name for recipe in recipes]
                )
                recipe = list(filter(lambda x: x.name == choice, recipes))[0]
            else:
                recipe = recipes[0]
        except IndexError:
            raise PaprikaUserError("No matching recipes were found.")

        created = edit_recipe_interactively(recipe)

        remote.upload_recipe(created)
        remote.notify()
