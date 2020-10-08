import argparse
import os
from typing import List

import enquiries
from rich.progress import track

from ..command import BaseCommand
from ..exceptions import PaprikaUserError
from ..remote import Remote, RemoteRecipe
from ..utils import get_password_for_email, edit_recipe_interactively


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Opens an editor allowing you to edit an existing paprika recipe."""

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--editor", default=os.environ.get("EDITOR", "vim"))
        parser.add_argument("email", type=str)
        parser.add_argument("search_terms", nargs="*", type=str)

    def handle(self) -> None:
        password = get_password_for_email(self.options.email)
        remote = Remote(self.options.email, password)

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
