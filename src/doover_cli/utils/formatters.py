import json

from pydoover.cloud.api.channel import Task

from .state import state


def format_agent_info(agent):
    if state.json:
        return json.dumps(agent.to_dict(), indent=4)

    fmt = f"""
    Agent Name: {agent.name}
    Agent Type: {agent.type}
    Agent Owner: {agent.owner_org}
    Agent ID: {agent.id}
    """
    return fmt


def format_channel_info(channel):
    if state.json:
        return json.dumps(channel.to_dict(), indent=4)

    fmt = f"""
    Channel Name: {channel.name}
    Channel Type: {str(channel.__class__.__name__)}
    Channel ID: {channel.id}

    Agent ID: {channel.agent_id}
    """
    # Agent Name: {channel.fetch_agent()}

    if isinstance(channel, Task) and channel.processor_id is not None:
        proc = channel.fetch_processor()
        fmt += f"""
    Processor ID: {channel.processor_id}
    Processor Name: {proc.name}
    """
    fmt += f"""
    Aggregate: {json.dumps(channel.aggregate, indent=4)}
    """
    return fmt
