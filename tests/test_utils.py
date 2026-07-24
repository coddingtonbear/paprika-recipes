import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from paprika_recipes import utils
from paprika_recipes.exceptions import PaprikaUserError
from paprika_recipes.recipe import BaseRecipe


class FakeEditor:
    """Stands in for subprocess.Popen, simulating how an editor saves."""

    def __init__(self, action):
        self._action = action
        self.invocations = []

    def __call__(self, args, *popen_args, **popen_kwargs):
        self.invocations.append(args)
        self._action(Path(args[1]))

        return Mock(wait=Mock(return_value=0))

    @property
    def editor_used(self) -> str:
        return self.invocations[0][0]


def save_by_rename(contents: str):
    """Save the way vim and friends do: write a new file, rename it over."""

    def action(path: Path) -> None:
        replacement = path.with_name(path.name + ".new")
        replacement.write_text(contents, encoding="utf-8")
        os.replace(replacement, path)

    return action


def save_in_place(contents: str):
    def action(path: Path) -> None:
        path.write_text(contents, encoding="utf-8")

    return action


def recipe_yaml(**overrides) -> str:
    data = {"name": "Edited Name", "ingredients": "1 onion"}
    data.update(overrides)
    return yaml.safe_dump(data)


@pytest.fixture
def recipe() -> BaseRecipe:
    return BaseRecipe(name="Original Name", ingredients="2 carrots")


class TestEditRecipeInteractively:
    def test_reads_back_edits_saved_by_rename(self, monkeypatch, recipe):
        editor = FakeEditor(save_by_rename(recipe_yaml()))
        monkeypatch.setattr(utils.subprocess, "Popen", editor)

        result = utils.edit_recipe_interactively(recipe)

        assert result.name == "Edited Name"
        assert result.ingredients == "1 onion"

    def test_reads_back_edits_saved_in_place(self, monkeypatch, recipe):
        editor = FakeEditor(save_in_place(recipe_yaml()))
        monkeypatch.setattr(utils.subprocess, "Popen", editor)

        result = utils.edit_recipe_interactively(recipe)

        assert result.name == "Edited Name"

    def test_preserves_unicode(self, monkeypatch, recipe):
        editor = FakeEditor(save_by_rename(recipe_yaml(name="Bánh Mì ½")))
        monkeypatch.setattr(utils.subprocess, "Popen", editor)

        result = utils.edit_recipe_interactively(recipe)

        assert result.name == "Bánh Mì ½"

    def test_uses_the_editor_it_was_given(self, monkeypatch, recipe):
        editor = FakeEditor(save_by_rename(recipe_yaml()))
        monkeypatch.setattr(utils.subprocess, "Popen", editor)

        utils.edit_recipe_interactively(recipe, editor="nano")

        assert editor.editor_used == "nano"

    def test_shows_the_original_recipe_to_the_editor(self, monkeypatch, recipe):
        seen = {}

        def action(path: Path) -> None:
            seen["contents"] = path.read_text(encoding="utf-8")
            save_by_rename(recipe_yaml())(path)

        monkeypatch.setattr(utils.subprocess, "Popen", FakeEditor(action))

        utils.edit_recipe_interactively(recipe)

        assert "Original Name" in seen["contents"]

    def test_aborts_when_the_file_is_emptied(self, monkeypatch, recipe):
        editor = FakeEditor(save_by_rename(""))
        monkeypatch.setattr(utils.subprocess, "Popen", editor)

        with pytest.raises(PaprikaUserError):
            utils.edit_recipe_interactively(recipe)

    def test_cleans_up_its_temporary_file(self, monkeypatch, recipe):
        paths = []

        def action(path: Path) -> None:
            paths.append(path)
            save_by_rename(recipe_yaml())(path)

        monkeypatch.setattr(utils.subprocess, "Popen", FakeEditor(action))

        utils.edit_recipe_interactively(recipe)

        assert paths
        assert not paths[0].exists()

    def test_cleans_up_after_an_aborted_edit(self, monkeypatch, recipe):
        paths = []

        def action(path: Path) -> None:
            paths.append(path)
            save_by_rename("")(path)

        monkeypatch.setattr(utils.subprocess, "Popen", FakeEditor(action))

        with pytest.raises(PaprikaUserError):
            utils.edit_recipe_interactively(recipe)

        assert paths
        assert not paths[0].exists()
