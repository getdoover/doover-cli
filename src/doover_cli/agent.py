from typer import Typer

from .utils.context import Context
from .utils.formatters import format_agent_info
from .utils.state import state

app = Typer(no_args_is_help=True)

@app.command(name="list")
def list_(ctx: Context):
    """List available agents"""
    agents = state.api.get_agent_list()
    for a in agents:
        print(format_agent_info(a))
