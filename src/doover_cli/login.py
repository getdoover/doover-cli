from datetime import datetime, timedelta, timezone
from typing import Annotated

import typer

from pydoover.cloud.api import Forbidden, NotFound, ConfigEntry
from typer import Typer

from .utils.api import setup_api
from .utils.prompt import QuestionaryPromptCommand
from .utils.state import state

app = Typer(no_args_is_help=True)


@app.command(cls=QuestionaryPromptCommand)
def login(
    username: Annotated[str, typer.Option(prompt="Doover username:")],
    password: Annotated[str, typer.Option(prompt="Doover password:", hide_input=True)],
    base_url: Annotated[
        str, typer.Option(prompt="Base API URL:")
    ] = "https://my.doover.com",
    profile_name: Annotated[str, typer.Option(prompt="Profile name:")] = "default",
):
    """Login to your doover account with a username / password"""
    username = username.strip()
    password = password.strip()
    base_url = base_url.strip("%").strip("/")
    profile = profile_name.strip()

    state.config_manager.create(
        ConfigEntry(
            profile,
            username=username,
            password=password,
            base_url=base_url,
        )
    )
    state.config_manager.current_profile = profile

    try:
        setup_api(None, state.config_manager, read=False)
        # self.api.login()
    except Exception as e:
        print("Login failed. Please try again.")
        if state.debug:
            raise e
        raise typer.Exit(1)

    state.config_manager.write()
    print("Login successful.")


@app.command(cls=QuestionaryPromptCommand)
def configure_token(
    token: Annotated[
        str, typer.Option(prompt="API Token:", help="Long-lived API token")
    ],
    agent_id: Annotated[
        str, typer.Option(prompt="Agent ID:", help="Default Agent ID to use.")
    ],
    base_url: Annotated[
        str, typer.Option(prompt="Base API URL:", help="Base URL for the Doover API.")
    ] = "https://my.doover.com",
    profile: Annotated[
        str,
        typer.Option(
            prompt="Profile name:", help="Profile name to set for this token."
        ),
    ] = "default",
    expiry: Annotated[
        str,
        typer.Option(
            prompt="Token expiry (in days):", help="Number of days until token expires."
        ),
    ] = None,
):
    """Configure your doover credentials with a long-lived token"""
    if profile in state.config_manager.entries:
        typer.confirm(
            "There's already a config entry with this profile. Do you want to overwrite it?",
            abort=True,
            default=False,
        )

    if expiry:
        try:
            expiry = datetime.now(timezone.utc) + timedelta(days=int(expiry.strip()))
        except ValueError:
            print(
                "I couldn't parse that expiry. I will set it to None which means no expiry."
            )
            expiry = None

    state.config_manager.create(
        ConfigEntry(
            profile,
            token=token,
            token_expires=expiry,
            base_url=base_url,
            agent_id=agent_id,
        )
    )
    state.config_manager.current_profile = profile

    setup_api(state.agent_id, state.config_manager, read=False)
    try:
        state.api.get_agent(state.agent_id)
    except Forbidden:
        print("Agent token was incorrect. Please try again.")
        raise typer.Exit(1)
    except NotFound:
        print("Agent ID or Base URL was incorrect. Please try again.")
        raise typer.Exit(1)
    except Exception:
        print("Base URL was incorrect. Please try again.")
        raise typer.Exit(1)
    else:
        state.config_manager.write()
        print("Successfully configured doover credentials.")
