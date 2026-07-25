"""Getting hold of an account's credentials, asking only when we have to.

Credentials live in two places, neither of which is a file we write.  The
password goes into the system keyring under the account's e-mail address, so
it is shared by every recipe directory belonging to that account and never
touches our own storage.  Which account a directory belongs to is recorded in
that directory's `.paprika/config.yaml`, so a directory carries its identity
around with it.

The point of splitting them that way is that there is nothing to set up in
advance and nothing to keep in step: the first `clone` asks for an e-mail and
a password, and nothing asks again.  A password that stops working is noticed
where it fails rather than in some separate place you have to remember to go
and fix, so changing it is just answering the prompt.
"""

from __future__ import annotations

from typing import Final

import keyring
from rich.console import Console
from rich.prompt import Prompt

from .cache import Cache
from .constants import APP_NAME
from .exceptions import AuthenticationError, PaprikaError
from .remote import Remote

#: How many times to let someone mistype a password before giving up.  Enough
#: for a typo, few enough that a wrong password does not look like a hang.
PASSWORD_ATTEMPTS: Final = 3


def ask_for_account(console: Console) -> str:
    """Ask which paprika account to use."""
    require_someone_to_ask(console, "No paprika account was named")

    while True:
        account = Prompt.ask("Paprika account e-mail", console=console).strip()

        if account:
            return account


def authenticate(account: str, domain: str, cache: Cache, console: Console) -> Remote:
    """Return a connection to `account` whose credentials we have confirmed.

    Logging in here rather than lazily on the first real request is what makes
    a wrong password a question instead of a crash: it costs nothing extra,
    since the token would have been fetched by that first request anyway.
    """
    stored = keyring.get_password(APP_NAME, account)

    if stored is not None:
        remote = Remote(account, stored, domain=domain, cache=cache)
        problem = login_error(remote)

        if problem is None:
            return remote

        console.print(
            f"[yellow]The stored password for {account} was not "
            f"accepted: {problem}[/yellow]"
        )

    require_someone_to_ask(console, f"No usable password is stored for {account}")

    return ask_for_password(account, domain, cache, console)


def ask_for_password(
    account: str, domain: str, cache: Cache, console: Console
) -> Remote:
    """Ask for a password, and store it once it is known to work.

    Nothing is written to the keyring until the password has actually logged
    in, so a typo cannot displace a working password with a broken one.
    """
    for remaining in reversed(range(PASSWORD_ATTEMPTS)):
        password = Prompt.ask(f"Password for {account}", password=True, console=console)
        remote = Remote(account, password, domain=domain, cache=cache)
        problem = login_error(remote)

        if problem is None:
            keyring.set_password(APP_NAME, account, password)
            console.print(f"[green]Password stored for {account}.[/green]")

            return remote

        console.print(f"[yellow]{problem}[/yellow]")

        if remaining:
            console.print(
                f"[yellow]{remaining} more "
                f"{'try' if remaining == 1 else 'tries'}.[/yellow]"
            )

    raise AuthenticationError(f"Could not log in to {account}.")


def login_error(remote: Remote) -> str | None:
    """None if the credentials work, otherwise why they did not.

    The reason is shown rather than swallowed, because "the server is
    unreachable" and "that is the wrong password" both stop you logging in but
    call for completely different responses from whoever is reading.
    """
    try:
        remote.bearer_token
    except PaprikaError as e:
        return str(e)

    return None


def require_someone_to_ask(console: Console, problem: str) -> None:
    """Refuse to prompt when there is nobody there to answer."""
    if console.is_interactive:
        return

    raise AuthenticationError(
        f"{problem}, and there is no terminal here to ask at. Run "
        "`paprika-recipes clone` once from a terminal to store your "
        "credentials in your system keyring."
    )
