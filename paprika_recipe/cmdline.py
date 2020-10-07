from argparse import ArgumentParser

from .command import get_installed_commands


def main():
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

    commands[args.command](args).handle()
