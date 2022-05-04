import argparse
import os
from typing import List

import questionary
from rich.progress import Progress, track

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

            if recipe.in_trash:
                continue

            for term in self.options.search_terms:
                if term.lower() not in recipe.name.lower():
                    matched = False
                    break

            if matched:
                recipes.append(recipe)

        try:
            if len(recipes) > 1:
                choice = questionary.select(
                    "Select a recipe to edit",
                    [
                        questionary.Choice(recipe.name, recipe.uid)
                        for recipe in sorted(recipes, key=lambda row: row.name)
                    ],
                ).ask()
                recipe = list(filter(lambda x: x.uid == choice, recipes))[0]
            else:
                recipe = recipes[0]
        except IndexError:
            raise PaprikaUserError("No matching recipes were found.")

        created = edit_recipe_interactively(recipe)

        with Progress() as pb:
            task_id = pb.add_task("Uploading Recipe", total=1)

            remote.upload_recipe(created)

            pb.update(task_id, completed=1)

        remote.notify()
