from getpass import getpass

import enquiries
import keyring

from ..command import BaseCommand
from ..constants import APP_NAME
from ..remote import Remote
from ..utils import save_config


class Command(BaseCommand):
    @classmethod
    def get_help(cls) -> str:
        return """Stores a paprika account password in your system keyring."""

    def handle(self) -> None:
        email = ""
        password = ""

        while not email:
            email = input("Email: ")

        while not password:
            password = getpass("Password: ")

        if Remote(email, password).bearer_token:
            keyring.set_password(APP_NAME, email, password)
            print(f"Password stored for {email}")

        if enquiries.confirm(f"Use {email} as your default account?"):
            self.config["default_account"] = email
            save_config(self.config)
