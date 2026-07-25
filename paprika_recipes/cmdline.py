import sys
from argparse import ArgumentParser
from typing import Final

from rich.console import Console
from rich.traceback import install as enable_rich_traceback

from .command import get_installed_commands
from .constants import ExitCode
from .exceptions import AuthenticationError, PaprikaError, PaprikaUserError

#: Which exit code each kind of failure earns, most specific first.
EXIT_CODES: Final[tuple[tuple[type[Exception], ExitCode], ...]] = (
    (AuthenticationError, ExitCode.AUTHENTICATION),
    (PaprikaUserError, ExitCode.USER),
    (PaprikaError, ExitCode.REMOTE),
)

#: How each kind of failure is coloured: red for something that went wrong out
#: there, yellow for something you can fix in here.
ERROR_STYLES: Final[dict[ExitCode, str]] = {
    ExitCode.AUTHENTICATION: "red",
    ExitCode.REMOTE: "red",
    ExitCode.USER: "yellow",
}


def exit_code_for(error: Exception) -> ExitCode:
    for error_class, code in EXIT_CODES:
        if isinstance(error, error_class):
            return code

    return ExitCode.INTERNAL


def main() -> None:
    sys.exit(run(sys.argv[1:]))


def run(argv: list[str] | None = None) -> ExitCode:
    enable_rich_traceback()
    commands = get_installed_commands()

    parser = ArgumentParser()
    parser.add_argument("--debugger", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    for cmd_name, cmd_class in commands.items():
        subparser = subparsers.add_parser(cmd_name, help=cmd_class.get_help() or None)
        cmd_class._add_arguments(subparser)

    args = parser.parse_args(argv)

    if args.debugger:
        import debugpy

        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()

    # Everything we say about a failure goes to stderr, so that a command's
    # actual output is the only thing on stdout and can be piped somewhere.
    console = Console(stderr=True)

    try:
        return commands[args.command](args).handle() or ExitCode.SUCCESS
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")

        return ExitCode.USER
    except (PaprikaError, PaprikaUserError) as e:
        code = exit_code_for(e)
        console.print(f"[{ERROR_STYLES[code]}]{e}[/{ERROR_STYLES[code]}]")

        return code
    except Exception:
        console.print_exception()

        return ExitCode.INTERNAL
