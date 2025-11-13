import os
import json
from pathlib import Path

import typer

from pydoover.cloud.api.application import Application

from .shell_commands import run


def get_app_directory(root: Path = None) -> Path:
    root_fp = root or Path()
    while not (root_fp / "doover_config.json").exists():
        if root_fp == Path("/"):
            raise FileNotFoundError(
                "doover_config.json not found. Please run this command from the application directory."
            )

        res = list(root_fp.rglob("doover_config.json"))
        if len(res) > 1:
            raise ValueError(
                "Multiple doover_config.json files found. Please navigate to the correct application directory."
            )
        elif len(res) == 0:
            root_fp = root_fp.parent.absolute()
        else:
            root_fp = res[0].parent.absolute()
            break

    return root_fp


def get_uv_path() -> Path:
    brew = Path("/opt/homebrew/bin/uv")
    if brew.exists():
        return brew

    uv_path = Path.home() / ".local" / "bin" / "uv"
    if not uv_path.exists():
        raise RuntimeError(
            "uv not found in your PATH. Please install it and try again."
        )
    return uv_path


def call_with_uv(*args, uv_run: bool = True, in_shell: bool = False):
    uv_path = get_uv_path()
    if uv_run:
        args = ["uv", "run"] + list(args)

    if in_shell:
        run(" ".join(str(r) for r in args))
    else:
        os.execl(str(uv_path.absolute()), *args)


def get_docker_path() -> Path:
    if Path("/usr/bin/docker").exists():
        docker_path = "/usr/bin/docker"
    elif Path("/usr/local/bin/docker").exists():
        docker_path = "/usr/local/bin/docker"
    else:
        raise RuntimeError(
            "Couldn't find docker installation. Make sure it is installed, in your PATH and try again."
        )
    return Path(docker_path)


def get_app_config(root_fp: Path) -> Application:
    config_path = root_fp / "doover_config.json"
    if not config_path.exists():
        print(f"Configuration file not found at {config_path}.")
        raise typer.Exit(1)

    with open(config_path, "r") as file:
        data = json.load(file)

    for k, v in data.items():
        if isinstance(v, dict) and "config_schema" in v:
            # config_schema bit of a prerequisite for an app config entry.
            return Application.from_config(v, root_fp)

    print(
        f"No application configuration found in the `doover_config.json` file at {root_fp}. "
        f"Make sure the `type` is set to `application` in the configuration."
    )
    raise typer.Exit(1)
