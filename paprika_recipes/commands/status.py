from rich.console import Console

from ..command import RepositoryCommand
from ..reporting import print_status


class Command(RepositoryCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Shows which recipe files have changed since the last sync."""

    def handle(self) -> None:
        # Deliberately offline: this answers "what have I changed?", which is
        # a question about the directory alone. Whether the *server* has moved
        # is what `pull` is for.
        print_status(Console(), self.repository.status())
