from enum import IntEnum
from importlib.metadata import PackageNotFoundError, version

APP_NAME = "paprika-recipes"

#: The host serving Paprika's sync API.  Configurable only so that a proxy can
#: be dropped in front of it; there is no other server to talk to.
DEFAULT_DOMAIN = "www.paprikaapp.com"

try:
    VERSION = version(APP_NAME)
except PackageNotFoundError:  # running from a source tree that was never installed
    VERSION = "0.0.0"

#: The v2 API answers `{"error": {"message": "Unrecognized client."}}` -- with a
#: 200, not a 4xx -- to any request whose User-Agent it does not recognise, and
#: what it recognises is the string Paprika's own iOS app sends.  The match is on
#: a prefix, so appending our own name and version still gets in; we do that
#: rather than send their string alone, because traffic from this program should
#: say that it came from this program.  The v1 login endpoint has no such check,
#: which is the only reason earlier releases could talk to it unadorned.
PAPRIKA_APP_USER_AGENT = (
    "Paprika 3/3.8.5 (com.hindsightlabs.paprika.ios.v3; build:80; iOS 26.5.2) "
    "Alamofire/5.2.2"
)
USER_AGENT = f"{PAPRIKA_APP_USER_AGENT} {APP_NAME}/{VERSION}"


class ExitCode(IntEnum):
    """What we exit with, so that a script can tell what happened.

    The distinction that earns its keep is between "the command ran, and the
    answer is that something needs you" and "the command could not run".  A
    script that syncs a directory nightly wants to retry a `REMOTE` failure and
    e-mail somebody about an `ATTENTION` one, and it cannot tell those apart
    from the output alone.
    """

    #: Everything asked for was done.
    SUCCESS = 0
    #: The command ran to completion, but left something for a person to do --
    #: a conflict, a recipe it refused to push, changes `status` was asked to
    #: report the existence of.
    ATTENTION = 1
    #: 2 is argparse's, for a malformed command line. Nothing else may use it.
    USAGE = 2
    #: We could not log in.
    AUTHENTICATION = 3
    #: Paprika could not be reached, or did not like what we sent it.
    REMOTE = 4
    #: Something about the directory or its files is wrong.
    USER = 5
    #: A bug in this program. 70 is sysexits.h's EX_SOFTWARE.
    INTERNAL = 70
