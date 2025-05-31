import os
import re

from datetime import datetime, timezone

from pydoover.cloud.api import Client
from pydoover.cloud.api import ConfigManager

from .misc import choose

KEY_MATCH = re.compile(r"[0-9a-z]{8}-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{12}")


def on_api_login(api: Client, config_manager: ConfigManager):
    config = config_manager.current

    config.agent_id = api.agent_id
    config.token = api.access_token.token
    config.token_expires = api.access_token.expires_at

    config_manager.write()


def setup_api(agent_id: str, config_manager: ConfigManager, read: bool = True):
    env_token = os.environ.get("DOOVER_API_TOKEN")
    if env_token:
        # shortcut for using an environment variable, e.g. in CI/CD pipelines
        api = Client(
            token=env_token,
            base_url=os.environ.get("DOOVER_API_BASE_URL", "https://my.doover.com"),
            agent_id=agent_id,
        )
        return api, resolve_agent_query(agent_id, api)

    if read:
        config_manager.read()

    config = config_manager.current
    if not config:
        raise RuntimeError(
            f"No configuration found for profile {config_manager.current_profile}. "
            f"Please use a different profile or run `doover login`"
        )

    if agent_id is None:
        agent_id = config.agent_id

    api: Client = Client(
        config.username,
        config.password,
        config.token,
        config.token_expires,
        config.base_url,
        agent_id,
        login_callback=lambda: on_api_login(api, config_manager),
    )

    if not (config.token and config.token_expires > datetime.now(timezone.utc)):
        api.login()

    return api, resolve_agent_query(agent_id, api)


def resolve_agent_query(agent_query: str, api: Client):
    if agent_query is None:
        return None

    id_match = KEY_MATCH.search(agent_query)
    if id_match:
        return api.get_agent(id_match.group(0))

    try:
        from fuzzywuzzy import process
    except ImportError:
        print(
            "Tried to use fuzzy matching without fuzzywuzzy installed. "
            "Please pass an agent ID, or install the extra packages."
        )
        return

    print("Fetching agents...")
    agents = {a.name: a for a in api.get_agent_list()}
    matches = process.extractBests(agent_query, agents.keys(), limit=5, score_cutoff=65)
    if len(matches) == 0:
        print(
            f"Could not resolve agent query: {agent_query}. Using default user agent ID."
        )
        return

    if len(matches) == 1 or len([m for m in matches if m[1] == 100]):
        agent_name, score = matches[0]
        # quick route, no menu required
        print(
            f"Using agent {agent_name} for API calls. (Query: {agent_query}, Score: {score}%)"
        )
        return agents[agent_name]

    options = [f"{m[0]} (Match: {m[1]}%)" for m in matches]
    selected = choose("Multiple agents found. Please select one:", options)
    agent_name = re.search(r"(.*) \(Match: \d+%\)", selected).group(1)
    print(f"Using agent {agent_name} for API calls. (Query: {agent_query})")
    return agents[agent_name]
