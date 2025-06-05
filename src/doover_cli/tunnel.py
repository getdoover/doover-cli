import os
import time

from typer import Typer

from .utils.api import AgentAnnotation, ProfileAnnotation
from .utils.misc import get_ip
from .utils.misc import choose
from .utils.state import state

app = Typer(no_args_is_help=True)


def create_tunnel(
    hostname: str,
    port: int,
    protocol: str,
    timeout: int,
    restrict_cidr: bool = True,
):
    tunnels = state.api.get_tunnels(state.agent_id)
    if restrict_cidr:
        my_ip = get_ip()
    else:
        my_ip = None

    tunnel = None
    for t in tunnels["tunnels"]:
        if t["hostname"] == hostname and t["port"] == port:
            tunnel = t
            break

    if tunnel:
        if (
            tunnel["timeout"] != timeout
            or tunnel["ip_restricted"] != restrict_cidr
            or (restrict_cidr and my_ip not in tunnel["ip_whitelist"])
        ):
            print(
                "Existing tunnel found, but with different settings. Editting tunnel..."
            )
            state.api.patch_tunnel(
                tunnel["key"],
                timeout=timeout,
                ip_restricted=restrict_cidr,
                ip_whitelist=[my_ip] if restrict_cidr else [],
            )
        print(f"Found existing tunnel: {tunnel['endpoint']}...")
        return tunnel

    print("No tunnel found. Opening tunnel... Please wait...")
    tunnel = state.api.create_tunnel(
        state.agent_id,
        hostname=hostname,
        port=port,
        protocol=protocol,
        name=f"{hostname}:{port}",
        ip_restricted=restrict_cidr,
        is_favourite=True,
        ip_whitelist=[my_ip] if restrict_cidr else [],
        timeout=timeout,
    )

    return tunnel


def wait_activate_tunnel(tunnel_id, wait_for_open: bool = True):
    state.api.activate_tunnel(tunnel_id)
    print(f"Activated tunnel {tunnel_id}.")

    if wait_for_open:
        print("Waiting for tunnel to open...")
        while True:
            tunnel = state.api.get_tunnel(tunnel_id)
            if tunnel["is_active"]:
                print("Tunnel is open.")
                break

            time.sleep(1)


def activate_deactivate_tunnel(tunnel_id: str = None, activate: bool = True):
    action = state.api.activate_tunnel if activate else state.api.deactivate_tunnel
    action_word = "activate" if activate else "deactivate"

    if tunnel_id:
        action(tunnel_id)
        print(f"Successfully {'activated' if activate else 'deactivated'} tunnel.")
        return

    tunnels = state.api.get_tunnels(state.agent_id)
    if not tunnels.get("tunnels", []):
        print("No tunnels found.")
        return

    options = [
        f"{tunnel['name']} ({tunnel['endpoint']})" for tunnel in tunnels["tunnels"]
    ]
    choice = choose("Select an agent:", options)
    tunnel = tunnels["tunnels"][choice]
    action(tunnel["key"])
    print(f"Successfully {action_word} tunnel.")


@app.command()
def get(_profile: ProfileAnnotation = None, _agent: AgentAnnotation = None):
    """Get tunnels for an agent"""
    tunnels = state.api.get_tunnels(state.agent_id)
    for tunnel in tunnels["tunnels"]:
        print(
            f"{tunnel['name']} ({tunnel['endpoint']}) - {'Active' if tunnel['is_active'] else 'Inactive'}"
        )


@app.command()
def activate(
    tunnel_id: str = None,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Activate a tunnel"""
    activate_deactivate_tunnel(tunnel_id, activate=True)


@app.command()
def deactivate(
    tunnel_id: str = None,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Deactivate a tunnel"""
    activate_deactivate_tunnel(tunnel_id, activate=False)


@app.command(name="open")
def open_(
    address: str,
    protocol: str = "http",
    timeout: int = 15,
    restrict_cidr: bool = True,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Open an arbitrary tunnel for a doover agent"""
    host, port = address.split(":")
    create_tunnel(host, int(port), protocol, timeout, restrict_cidr)


@app.command()
def open_ssh(
    timeout: int = 15,
    restrict_cidr: bool = True,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Open an SSH tunnel for a doover agent"""
    tunnel = create_tunnel("127.0.0.1", 22, "tcp", timeout, restrict_cidr)
    print(tunnel)
    if not tunnel["is_active"]:
        wait_activate_tunnel(tunnel["key"], True)

    host, port = tunnel["endpoint"].split(":")

    username = input("Please enter your SSH username: ")

    print(
        f"Opening SSH session with host: {host}, port: {port}, username: {username}..."
    )
    os.execl("/usr/bin/ssh", "ssh", f"{username}@{host}", "-p", port)


@app.command()
def close_all(_profile: ProfileAnnotation = None, _agent: AgentAnnotation = None):
    """Close all tunnels for a doover agent"""
    channel = state.api.get_channel_named("tunnels", state.agent_id)
    channel.publish({"to_close": channel.aggregate["open"]})
    print("Successfully closed all tunnels.")
