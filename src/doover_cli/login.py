import traceback
from datetime import datetime, timedelta, timezone
from getpass import getpass

from pydoover.cloud.api import Forbidden, NotFound
from typer import Typer

from .utils.api import setup_api
from .utils.config import ConfigEntry, NotSet
from .utils.state import state

app = Typer(no_args_is_help=True)


@app.command()
def login():
    """Login to your doover account with a username / password"""
    username = input("Please enter your username: ").strip()
    password = getpass("Please enter your password: ").strip()
    base_url = input("Please enter the base API URL: ").strip("%").strip("/")
    profile_name = input(
        "Please enter this profile name (defaults to default): "
    ).strip()
    profile = profile_name if profile_name != "" else "default"

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
    except Exception:
        print("Login failed. Please try again.")
        if state.debug:
            traceback.print_exc()
        return login()

    state.config_manager.write()
    print("Login successful.")


@app.command()
def configure_token():
    """Configure your doover credentials with a long-lived token"""
    configure_token_impl()


def configure_token_impl(
    token: str = None,
    agent_id: str = None,
    base_url: str = None,
    expiry=NotSet,
    overwrite: bool = False,
):
    if not token:
        token = input("Please enter your agent token: ").strip()
        # self.config_manager.current.token = token.strip()
    if not agent_id:
        agent_id = input("Please enter your Agent ID: ").strip()
        # self.config_manager.agent_id = agent_id.strip()
    if not base_url:
        base_url = input("Please enter your base API url: ").strip("%").strip("/")
        # self.config.base_url = base_url
    if expiry is NotSet:
        print(
            "This token is intended to be a long-lived token."
            "I will remind you to reconfigure the token when this expiry is exceeded."
        )
        expiry_days = input(
            "Please enter the number of days (approximately) until expiration: "
        )
        try:
            expiry = datetime.now(timezone.utc) + timedelta(days=int(expiry_days))
        except ValueError:
            print(
                "I couldn't parse that expiry. I will set it to None which means no expiry."
            )
            expiry = None

        # self.config.token_expiry = expiry

    profile_name = input("Please enter this profile's name [default]: ")
    profile = profile_name or "default"

    if profile in state.config_manager.entries and not overwrite:
        p = input(
            "There's already a config entry with this profile. Do you want to overwrite it? [y/N]"
        )
        if not p.startswith("y"):
            print("Exitting...")
            return

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
        return configure_token_impl(
            agent_id=agent_id, base_url=base_url, expiry=expiry, overwrite=True
        )
    except NotFound:
        print("Agent ID or Base URL was incorrect. Please try again.")
        return configure_token_impl(token=token, expiry=expiry, overwrite=True)
    except Exception:
        print("Base URL was incorrect. Please try again.")
        return configure_token_impl(
            token=token, agent_id=agent_id, expiry=expiry, overwrite=True
        )
    else:
        state.config_manager.write()
        print("Successfully configured doover credentials.")
