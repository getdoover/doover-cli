"""Console entry point for `doover`."""

import sys


def main() -> None:
    from .tunnel_exec import maybe_exec

    maybe_exec(sys.argv[1:])

    from .cli import main as cli_main

    cli_main()
