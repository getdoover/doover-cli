"""Hand `doover ssh` / `doover tunnel` to the `doover-tunnel` binary.

The binary does the whole job itself (device lookup, session, forwarding),
so the console entry point calls `maybe_exec` before importing the rest of
the CLI: that import is most of a second, the binary starts in milliseconds.
This module must stay free of heavy imports for the same reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

INSTALL_HINT = (
    "doover-tunnel is not installed alongside doover-cli. Reinstall with "
    "`pip install -U doover-cli` (or `uv tool install -U doover-cli`)."
)

# doover verb -> doover-tunnel subcommand. Both sides take the same flags.
FAST_COMMANDS = {"ssh": "ssh", "tunnel": "open"}


def find_binary() -> str | None:
    """The `doover-tunnel` binary the `doover-tunnel` wheel installs next to us."""
    name = "doover-tunnel.exe" if os.name == "nt" else "doover-tunnel"
    candidates = [
        Path(sys.argv[0]).resolve().parent / name,
        Path(sysconfig.get_path("scripts")) / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("doover-tunnel")


def exec_binary(args: list[str]) -> None:
    if os.name == "nt":
        sys.exit(subprocess.call(args))
    os.execv(args[0], args)


def fast_args(argv: list[str]) -> list[str] | None:
    """Binary arguments for `argv` (everything after `doover`), or None when
    the Python CLI should handle it: another command, or a bare `doover ssh`
    / `doover tunnel`, which prompts for the device interactively."""
    if len(argv) < 2 or argv[0] not in FAST_COMMANDS:
        return None
    return [FAST_COMMANDS[argv[0]], *argv[1:]]


def maybe_exec(argv: list[str]) -> None:
    args = fast_args(argv)
    if args is None:
        return
    binary = find_binary()
    if binary is None:
        return
    exec_binary([binary, *args])
