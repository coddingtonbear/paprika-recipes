from io import StringIO

import pytest
from rich.console import Console

from paprika_recipes import credentials
from paprika_recipes.cache import NullCache
from paprika_recipes.exceptions import AuthenticationError, RequestError

ACCOUNT = "cook@example.com"
RIGHT = "correct-horse"
WRONG = "battery-staple"


class FakeKeyring:
    """The system keyring, minus the system."""

    def __init__(self, **stored: str):
        self.stored = dict(stored)

    def get_password(self, service: str, account: str) -> str | None:
        return self.stored.get(account)

    def set_password(self, service: str, account: str, password: str) -> None:
        self.stored[account] = password


class FakeRemote:
    """A paprika account that accepts exactly one password."""

    def __init__(self, email, password, domain=None, cache=None):
        self.email = email
        self.password = password

    @property
    def bearer_token(self) -> str:
        if self.password != RIGHT:
            raise RequestError("POST /api/v2/account/login/ returned an error: Invalid")

        return "a-token"


class OfflineRemote(FakeRemote):
    """An account we cannot reach at all, whatever the password."""

    @property
    def bearer_token(self) -> str:
        raise RequestError("Expected a JSON response, but received: <html>502")


@pytest.fixture
def console() -> Console:
    return Console(file=StringIO(), force_interactive=True, force_terminal=True)


@pytest.fixture
def keyring(monkeypatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "keyring", fake)

    return fake


@pytest.fixture
def remote(monkeypatch) -> type[FakeRemote]:
    monkeypatch.setattr(credentials, "Remote", FakeRemote)

    return FakeRemote


def answer(monkeypatch, *responses: str) -> list[str]:
    """Queue up what the person at the keyboard types."""
    remaining = list(responses)
    asked: list[str] = []

    def ask(prompt, **kwargs):
        asked.append(prompt)

        return remaining.pop(0)

    monkeypatch.setattr(credentials.Prompt, "ask", staticmethod(ask))

    return asked


def authenticate(console):
    return credentials.authenticate(ACCOUNT, "example.com", NullCache(), console)


class TestAStoredPassword:
    def test_is_used_without_asking(self, console, keyring, remote, monkeypatch):
        keyring.stored[ACCOUNT] = RIGHT
        asked = answer(monkeypatch)

        assert authenticate(console).password == RIGHT
        assert asked == []

    def test_is_replaced_when_the_server_rejects_it(
        self, console, keyring, remote, monkeypatch
    ):
        keyring.stored[ACCOUNT] = WRONG
        answer(monkeypatch, RIGHT)

        assert authenticate(console).password == RIGHT
        assert keyring.stored[ACCOUNT] == RIGHT

    def test_explains_why_it_was_rejected(self, console, keyring, remote, monkeypatch):
        keyring.stored[ACCOUNT] = WRONG
        answer(monkeypatch, RIGHT)

        authenticate(console)

        assert "was not accepted" in console.file.getvalue()


class TestAskingForAPassword:
    def test_stores_one_that_works(self, console, keyring, remote, monkeypatch):
        answer(monkeypatch, RIGHT)

        authenticate(console)

        assert keyring.stored == {ACCOUNT: RIGHT}

    def test_never_stores_one_that_does_not(
        self, console, keyring, remote, monkeypatch
    ):
        """A typo must not displace a working password with a broken one."""
        answer(monkeypatch, WRONG, WRONG, WRONG)

        with pytest.raises(AuthenticationError, match="Could not log in"):
            authenticate(console)

        assert keyring.stored == {}

    def test_allows_a_typo(self, console, keyring, remote, monkeypatch):
        answer(monkeypatch, WRONG, RIGHT)

        assert authenticate(console).password == RIGHT

    def test_gives_up_after_a_few_attempts(self, console, keyring, remote, monkeypatch):
        asked = answer(monkeypatch, *[WRONG] * credentials.PASSWORD_ATTEMPTS)

        with pytest.raises(AuthenticationError):
            authenticate(console)

        assert len(asked) == credentials.PASSWORD_ATTEMPTS

    def test_says_why_when_the_server_is_unreachable(
        self, console, keyring, monkeypatch
    ):
        """A network failure should not read as "you typed it wrong".

        We cannot tell the two apart from the outside -- both are the server
        declining to hand over a token -- so we show the reason rather than
        summarising it, and let the reader draw the obvious conclusion.
        """
        monkeypatch.setattr(credentials, "Remote", OfflineRemote)
        answer(monkeypatch, *[RIGHT] * credentials.PASSWORD_ATTEMPTS)

        with pytest.raises(AuthenticationError):
            authenticate(console)

        assert "502" in console.file.getvalue()


class TestWithNobodyThere:
    """Nothing may block on a prompt in a cron job or a pipeline."""

    @pytest.fixture
    def console(self) -> Console:
        return Console(file=StringIO())

    def test_refuses_to_ask_for_a_password(self, console, keyring, remote):
        with pytest.raises(AuthenticationError, match="no terminal here"):
            authenticate(console)

    def test_refuses_to_ask_for_an_account(self, console):
        with pytest.raises(AuthenticationError, match="no terminal here"):
            credentials.ask_for_account(console)

    def test_still_uses_a_stored_password(self, console, keyring, remote):
        keyring.stored[ACCOUNT] = RIGHT

        assert authenticate(console).password == RIGHT


class TestAskingForAnAccount:
    def test_returns_what_was_typed(self, console, monkeypatch):
        answer(monkeypatch, "  cook@example.com  ")

        assert credentials.ask_for_account(console) == ACCOUNT

    def test_asks_again_when_nothing_was_typed(self, console, monkeypatch):
        asked = answer(monkeypatch, "", "   ", ACCOUNT)

        assert credentials.ask_for_account(console) == ACCOUNT
        assert len(asked) == 3
