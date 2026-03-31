import subprocess
from pathlib import Path

import typer
from rich import print

from .sentry import capture_handled_exception


def run(command, cwd: Path | None = None):
    """Run a shell command and return the output."""

    print(f"[bold green]Running command: [/bold green]{command}")
    try:
        subprocess.run(command, shell=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(
            f"[bold red]Command [blue]'{command}'[/blue] failed with error[/bold red]"
        )
        capture_handled_exception(
            e,
            command="shell.run",
            message=f"Command '{command}' failed with error",
        )
        raise typer.Exit(1)
