import json

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

    channel_key = f"{channel.owner_id}:{channel.name}"
    aggregate = channel.aggregate.to_dict() if channel.aggregate is not None else None
    fmt = f"""
    Channel Name: {channel.name}
    Channel Type: {str(channel.__class__.__name__)}
    Channel Key: {channel_key}
    Agent ID: {channel.owner_id}
    Private: {channel.is_private}
    """
    if channel.message_schema is not None:
        fmt += f"""
    Message Schema: {json.dumps(channel.message_schema, indent=4)}
    """
    if channel.aggregate_schema is not None:
        fmt += f"""
    Aggregate Schema: {json.dumps(channel.aggregate_schema, indent=4)}
    """
    fmt += f"""
    Aggregate: {json.dumps(aggregate, indent=4)}
    """
    return fmt
