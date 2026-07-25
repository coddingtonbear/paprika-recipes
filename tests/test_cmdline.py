import argparse
import json
import sys
from typing import Any

import pytest

from paprika_recipes.cmdline import exit_code_for, run
from paprika_recipes.commands import pull
from paprika_recipes.constants import ExitCode
from paprika_recipes.exceptions import (
    AuthenticationError,
    PaprikaError,
    PaprikaUserError,
    RequestError,
)
from paprika_recipes.remote import RemoteRecipe
from paprika_recipes.reporting import JSON_VERSION
from paprika_recipes.repository import Repository, RepositoryConfig, Status


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


class TestNamingAnAccount:
    def test_clone_will_not_guess(self):
        """There is no default account to fall back on, by design."""
        with pytest.raises(SystemExit) as exit_info:
            run(["clone"])

        assert exit_info.value.code == ExitCode.USAGE

    def test_a_sync_uses_the_account_its_directory_was_cloned_from(self, cloned):
        cloned.save_config(RepositoryConfig(account="me@example.com"))

        command = pull.Command(argparse.Namespace(account="", directory=cloned.root))

        assert command.get_account() == "me@example.com"

    def test_an_account_named_on_the_command_line_wins(self, cloned):
        """Which is how a directory is copied into another account."""
        cloned.save_config(RepositoryConfig(account="me@example.com"))

        command = pull.Command(
            argparse.Namespace(account="you@example.com", directory=cloned.root)
        )

        assert command.get_account() == "you@example.com"


class TestJsonOutput:
    def parse(self, capsys) -> dict:
        """Read what a command wrote to stdout, which must be JSON and nothing else."""
        return json.loads(capsys.readouterr().out)

    def test_writes_a_versioned_document(self, cloned, capsys):
        run(["status", "--json", "--directory", str(cloned.root)])

        assert self.parse(capsys)["version"] == JSON_VERSION

    def test_describes_a_change(self, cloned, capsys):
        next(cloned.working_paths()).unlink()

        run(["status", "--json", "--directory", str(cloned.root)])
        (recipe,) = self.parse(capsys)["recipes"]

        assert recipe["name"] == "Khachapuri"
        assert recipe["status"] == "deleted"
        assert recipe["conflicted"] is False

    def test_counts_what_it_did_not_list(self, cloned, capsys):
        run(["status", "--json", "--directory", str(cloned.root)])

        assert self.parse(capsys) == {
            "version": JSON_VERSION,
            "unchanged": 1,
            "recipes": [],
        }

    def test_uses_stable_names_rather_than_the_ones_on_screen(self, cloned, capsys):
        """`deleted` is the enum's value; `deleted:` is a label we may reword."""
        next(cloned.working_paths()).unlink()

        run(["status", "--json", "--directory", str(cloned.root)])
        (recipe,) = self.parse(capsys)["recipes"]

        assert recipe["status"] in {status.value for status in Status}

    def test_says_a_recipe_has_no_uid_rather_than_inventing_one(self, cloned, capsys):
        (cloned.root / "Mine.md").write_text("---\n---\n\n# Mine\n", encoding="utf-8")

        run(["status", "--json", "--directory", str(cloned.root)])
        (recipe,) = (
            entry for entry in self.parse(capsys)["recipes"] if entry["name"] == "Mine"
        )

        assert recipe["uid"] is None

    def test_keeps_everything_meant_for_a_person_off_stdout(self, cloned):
        command = pull.Command(
            argparse.Namespace(json=True, account="", directory=cloned.root)
        )

        assert command.console.file is sys.stderr

    def test_will_not_stop_to_ask_a_script_a_question(self, cloned):
        """A prompt a script cannot see is indistinguishable from a hang."""
        command = pull.Command(
            argparse.Namespace(json=True, account="", directory=cloned.root)
        )

        assert not command.console.is_interactive

    def test_still_talks_to_a_person_on_stdout(self, cloned):
        command = pull.Command(
            argparse.Namespace(json=False, account="", directory=cloned.root)
        )

        assert command.console.file is sys.stdout
