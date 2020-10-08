from argparse import ArgumentParser

from rich.console import Console
from rich.traceback import install as enable_rich_traceback

from .command import get_installed_commands
from .exceptions import PaprikaError, PaprikaUserError


def main():
    enable_rich_traceback()
    commands = get_installed_commands()

    parser = ArgumentParser()
    parser.add_argument("--debugger", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    for cmd_name, cmd_class in commands.items():
        parser_kwargs = {}

        cmd_help = cmd_class.get_help()
        if cmd_help:
            parser_kwargs["help"] = cmd_help

        subparser = subparsers.add_parser(cmd_name, **parser_kwargs)
        cmd_class.add_arguments(subparser)

    args = parser.parse_args()

    if args.debugger:
        import debugpy

        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()

    console = Console()

    try:
        commands[args.command](args).handle()
    except PaprikaError as e:
        console.print(f"[red]{e}[/red]")
    except PaprikaUserError as e:
        console.print(f"[yellow]{e}[/yellow]")
    except Exception:
        console.print_exception()
