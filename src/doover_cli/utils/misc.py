from typing import Any

import requests
from rich.prompt import Prompt


def get_ip():
    return requests.get("https://api.ipify.org").text

def choose(title: str, options: list[Any]) -> Any:
    print(title)
    print("\n".join(options))
    agent = Prompt.ask("Choose one: ", choices=[str(n) for n in range(1, len(options) + 1)])
    return options[int(agent)]

