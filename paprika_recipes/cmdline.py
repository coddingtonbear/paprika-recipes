from argparse import ArgumentParser

from rich.console import Console
from rich.traceback import install as enable_rich_traceback

from .command import get_installed_commands
from .exceptions import PaprikaError, PaprikaUserError
from .utils import get_config


def main():
    enable_rich_traceback()
    commands = get_installed_commands()
    config = get_config()

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
        cmd_class._add_arguments(subparser, config)

    args = parser.parse_args()

    if args.debugger:
        import debugpy

        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()

    console = Console()

    try:
        commands[args.command](config, args).handle()
    except PaprikaError as e:
        console.print(f"[red]{e}[/red]")
    except PaprikaUserError as e:
        console.print(f"[yellow]{e}[/yellow]")
    except Exception:
        console.print_exception()
