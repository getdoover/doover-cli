"""Doover CLI.

Importing the package is deliberately cheap: `entry.main` hands `doover ssh`
and `doover tunnel` to the doover-tunnel binary before `cli` (typer, pydoover,
docker, ...) loads. `app` and `main` are still reachable here, lazily.
"""

__version__ = "0.7.0"


def __getattr__(name: str):
    if name in ("app", "main", "sentry_utils"):
        from . import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
