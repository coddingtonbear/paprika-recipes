from typing import Any

import pytest

from paprika_recipes.cmdline import exit_code_for, run
from paprika_recipes.constants import ExitCode
from paprika_recipes.exceptions import (
    AuthenticationError,
    PaprikaError,
    PaprikaUserError,
    RequestError,
)
from paprika_recipes.remote import RemoteRecipe
from paprika_recipes.repository import Repository


def make_recipe(**overrides) -> RemoteRecipe:
    data: dict[str, Any] = {
        "name": "Khachapuri",
        "ingredients": "1 tsp salt",
        "directions": "Combine.",
    }
    data.update(overrides)

    return RemoteRecipe(**data)


@pytest.fixture
def cloned(tmp_path) -> Repository:
    repository = Repository.initialize(tmp_path)
    repository.store(make_recipe())

    return repository


class TestChoosingAnExitCode:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (AuthenticationError("nope"), ExitCode.AUTHENTICATION),
            (RequestError("500"), ExitCode.REMOTE),
            (PaprikaError("boom"), ExitCode.REMOTE),
            (PaprikaUserError("your fault"), ExitCode.USER),
            (ValueError("ours"), ExitCode.INTERNAL),
        ],
    )
    def test_maps_each_kind_of_failure(self, error, expected):
        assert exit_code_for(error) == expected

    def test_prefers_the_most_specific_match(self):
        """AuthenticationError is a PaprikaError; it must not be read as one."""
        assert exit_code_for(AuthenticationError("nope")) == ExitCode.AUTHENTICATION


class TestRunning:
    def test_succeeds_on_a_clean_directory(self, cloned):
        assert run(["status", "--directory", str(cloned.root)]) == ExitCode.SUCCESS

    def test_reports_a_directory_that_is_not_a_repository(self, tmp_path):
        somewhere_else = tmp_path / "elsewhere"
        somewhere_else.mkdir()

        assert run(["status", "--directory", str(somewhere_else)]) == ExitCode.USER

    def test_says_nothing_about_local_changes_unless_asked(self, cloned):
        next(cloned.working_paths()).unlink()

        assert run(["status", "--directory", str(cloned.root)]) == ExitCode.SUCCESS

    def test_reports_local_changes_when_asked(self, cloned):
        next(cloned.working_paths()).unlink()

        assert (
            run(["status", "--exit-code", "--directory", str(cloned.root)])
            == ExitCode.ATTENTION
        )

    def test_reports_nothing_when_asked_and_there_is_nothing(self, cloned):
        assert (
            run(["status", "--exit-code", "--directory", str(cloned.root)])
            == ExitCode.SUCCESS
        )

    def test_reserves_argparses_own_exit_code(self):
        """2 belongs to argparse; nothing we return may collide with it."""
        with pytest.raises(SystemExit) as exit_info:
            run(["status", "--nonsense"])

        assert exit_info.value.code == ExitCode.USAGE
        assert ExitCode.USAGE not in {
            code for code in ExitCode if code is not ExitCode.USAGE
        }
