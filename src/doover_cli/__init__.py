import typer

from .apps import app as apps_app
from .config import app as config_app
from .simulators import app as simulators_app

app = typer.Typer()
app.add_typer(apps_app, name="app", help="Manage applications and their configurations.")
app.add_typer(config_app, name="config", help="Manage app schemas.")
app.add_typer(simulators_app, name="simulator", help="Manage simulators and their configurations.")

def main():
    """
    Main entry point for the Doover CLI.
    """
    app()
