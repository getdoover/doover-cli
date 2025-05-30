import subprocess

import typer
from rich import print


def run(command):
    """Run a shell command and return the output."""

    print(f"[bold green]Running command: [/bold green]{command}")
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(
            f"[bold red]Command '{command}' failed with error: [/bold red]{e.stderr.strip()}"
        )
        raise typer.Exit(1)
