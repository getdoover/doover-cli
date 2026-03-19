from typer import Typer

from .utils.api import ProfileAnnotation, exit_for_unsupported_control_command

app = Typer(no_args_is_help=True)


@app.command(name="list")
def list_(_profile: ProfileAnnotation = None):
    """List available agents."""
    _ = _profile
    exit_for_unsupported_control_command("agent.list")
