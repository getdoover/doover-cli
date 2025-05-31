import subprocess
from typer import Typer, Context

app = Typer(no_args_is_help=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def platform(ctx: Context):
    """Interact with a platform interface gRPC server."""
    subprocess.run("pydoover platform " + " ".join(ctx.args), shell=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def device_agent(ctx: Context):
    """Interact with a device agent gRPC server."""
    subprocess.run("pydoover device_agent " + " ".join(ctx.args), shell=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def tunnel(ctx: Context):
    """Interact with a tunnel gRPC server."""
    subprocess.run("pydoover tunnel " + " ".join(ctx.args), shell=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def modbus(ctx: Context):
    """Interact with a modbus gRPC server."""
    subprocess.run("pydoover modbus " + " ".join(ctx.args), shell=True)
