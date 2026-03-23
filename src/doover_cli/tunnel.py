from typer import Typer

from .utils.api import AgentAnnotation, ProfileAnnotation, exit_for_unsupported_control_command

app = Typer(no_args_is_help=True)


@app.command()
def get(_profile: ProfileAnnotation = None, _agent: AgentAnnotation = None):
    """Get tunnels for an agent."""
    _ = (_profile, _agent)
    exit_for_unsupported_control_command("tunnel.get")


@app.command()
def activate(
    tunnel_id: str | None = None,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Activate a tunnel."""
    _ = (tunnel_id, _profile, _agent)
    exit_for_unsupported_control_command("tunnel.activate")


@app.command()
def deactivate(
    tunnel_id: str | None = None,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Deactivate a tunnel."""
    _ = (tunnel_id, _profile, _agent)
    exit_for_unsupported_control_command("tunnel.deactivate")


@app.command(name="open")
def open_(
    address: str,
    protocol: str = "http",
    timeout: int = 15,
    restrict_cidr: bool = True,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Open an arbitrary tunnel for a doover agent."""
    _ = (address, protocol, timeout, restrict_cidr, _profile, _agent)
    exit_for_unsupported_control_command("tunnel.open")


@app.command()
def open_ssh(
    timeout: int = 15,
    restrict_cidr: bool = True,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Open an SSH tunnel for a doover agent."""
    _ = (timeout, restrict_cidr, _profile, _agent)
    exit_for_unsupported_control_command("tunnel.open-ssh")


@app.command()
def close_all(_profile: ProfileAnnotation = None, _agent: AgentAnnotation = None):
    """Close all tunnels for a doover agent."""
    _ = (_profile, _agent)
    exit_for_unsupported_control_command("tunnel.close-all")
