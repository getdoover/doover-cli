import copy
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess

from urllib.parse import urlencode
from pathlib import Path
from enum import Enum

import rich
from pydoover.cloud.api import HTTPException
from typing_extensions import Annotated

import requests
import typer
import questionary

from docker.errors import ImageNotFound

from .utils.api import ProfileAnnotation
from .utils.apps import get_app_directory, call_with_uv, get_docker_path, get_app_config
from .utils.prompt import QuestionaryPromptCommand
from .utils.state import state
from .utils.shell_commands import run as shell_run

CHANNEL_VIEWER = "https://my.doover.com/channels/dda"
TEMPLATE_REPO = "https://api.github.com/repos/getdoover/app-template/tarball/main"

VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9-_]+$")
IP_PATTERN = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
HOSTNAME_PATTERN = re.compile(r"(?P<host>[a-zA-Z0-9_]*)-*(?P<serial>[0-9a-zA-Z]{6})")

app = typer.Typer(no_args_is_help=True)


class AppType(Enum):
    DEVICE = "device"
    INTEGRATION = "integration"


class SimulatorType(Enum):
    MODBUS = "modbus"
    PLATFORM = "platform"
    MIXED = "mixed"
    CHANNELS = "channels"


class ContainerRegistry(Enum):
    GITHUB_INT = "ghcr.io/getdoover"
    GITHUB_OTHER = "ghcr.io/other"
    DOCKERHUB_INT = "DockerHub (spaneng)"
    DOCKERHUB_OTHER = "DockerHub (other)"


def extract_archive(archive_path: pathlib.Path):
    """Extract an archive (tar, gz, zip) to a temporary directory and return the path to the extracted directory.

    Accounts for archives which rename the directory e.g. Github archives.
    """
    # this supports either tar, gz or zip files.
    extract_path = archive_path
    while extract_path.suffix in {".tar", ".gz", ".zip"}:
        extract_path = extract_path.with_suffix("")

    shutil.unpack_archive(archive_path, extract_path)
    if len(os.listdir(extract_path)) == 1:
        # get the inner folder
        extract_path = next(extract_path.iterdir())

    return extract_path


@app.command(cls=QuestionaryPromptCommand)
def create(
    name: Annotated[str, typer.Option(prompt="What is the name of your app?")],
    description: Annotated[
        str,
        typer.Option(
            prompt="Description (tell me a little about your app - what does it do?)"
        ),
    ],
    # type_: Annotated[AppType, typer.Option(prompt=True)] = AppType.DEVICE.value,
    # simulator: Annotated[
    #     SimulatorType, typer.Option(prompt=True)
    # ] = SimulatorType.MIXED.value,
    git: Annotated[
        bool, typer.Option(prompt="Would you like me to initiate a git repository?")
    ] = True,
    # cicd: Annotated[
    #     bool,
    #     typer.Option(prompt="Do you want to enable CI/CD for your app?"),
    # ] = True,
    container_registry: Annotated[
        ContainerRegistry,
        typer.Option(prompt="What is the container registry for your app?"),
    ] = ContainerRegistry.GITHUB_INT.value,
    owner_org_key: Annotated[
        str,
        typer.Option(
            prompt="What is the owner organisation's key (on Doover)? (leave blank if you don't know)"
        ),
    ] = "",
    container_profile_key: Annotated[
        str,
        typer.Option(
            prompt="What is the container registry profile key on Doover? (leave blank if you don't know)"
        ),
    ] = "",
):
    """Create an application with a walk-through wizard.

    This will create a new directory with the name of your app, and populate it with a template application.
    """
    name_as_path = name.lower().replace(" ", "-").replace("_", "-")
    if not VALID_NAME_PATTERN.match(name_as_path):
        raise ValueError(
            f"Invalid app name: {name}. Only alphanumeric characters, dashes, and underscores are allowed."
        )

    path = Path(name_as_path)
    if path.exists():
        typer.confirm("Path already exists. Do you want to delete it?", abort=True)
        typer.confirm("Are you absolutely sure? (Please double check...)", abort=True)
        shutil.rmtree(path)

    name_as_pascal_case = "".join(word.capitalize() for word in name_as_path.split("-"))
    name_as_snake_case = "_".join(name_as_path.split("-"))

    if container_registry is ContainerRegistry.GITHUB_OTHER:
        resp = questionary.text(
            "You selected an 'other' GitHub Packages registry. "
            "Please enter your GitHub organisation name, or GitHub username:"
        ).unsafe_ask()
        container_registry = f"ghcr.io/{resp}"
    elif container_registry is ContainerRegistry.DOCKERHUB_OTHER:
        container_registry = questionary.text(
            "You selected an 'other' DockerHub repository. "
            "Please enter the repository name (e.g spaneng):"
        ).unsafe_ask()
    elif container_registry is ContainerRegistry.DOCKERHUB_INT:
        container_registry = "spaneng"
    else:
        container_registry = container_registry.value

    print("Fetching template repository...")
    data = requests.get(TEMPLATE_REPO)
    if data.status_code != 200:
        raise Exception(f"Failed to fetch template repository: {data.status_code}")

    tmp_path = Path("/tmp/app-template.tar.gz")
    tmp_path.write_bytes(data.content)
    # Extract the tarball
    extracted_path = extract_archive(tmp_path)
    shutil.move(extracted_path, path)
    shutil.move(path / "src" / "app_template", path / "src" / name_as_snake_case)

    print("Renaming template files...")
    for file in (path / "pyproject.toml", path / "README.md", *path.rglob("*.py")):
        file: pathlib.Path
        try:
            contents: str = file.read_text()
        except FileNotFoundError:
            print(f"Something strange happened while correcting {file.name}")
            continue

        replacements = [
            ("SampleConfig", f"{name_as_pascal_case}Config"),
            ("SampleApplication", f"{name_as_pascal_case}Application"),
            ("SampleUI", f"{name_as_pascal_case}UI"),
            ("SampleState", f"{name_as_pascal_case}State"),
            ("sample_application", name_as_snake_case),
            ("app_template", name_as_snake_case),
            ("app-template", name_as_path),
        ]

        for old, new in replacements:
            contents = contents.replace(old, new)

        file.write_text(contents)

    # write config
    print("Updating config...")
    subprocess.run(
        "uv run app_config.py",
        shell=True,
        cwd=path / "src" / name_as_snake_case,
        capture_output=True,
    )

    config_path = path / "doover_config.json"
    content = json.loads(config_path.read_text())
    content[name_as_snake_case] = copy.deepcopy(content["sample_application"])
    del content["sample_application"]
    del content[name_as_snake_case]["key"]
    content[name_as_snake_case].update(
        {
            "name": name_as_snake_case,
            "display_name": name,
            "description": description,
            "type": "DEV",
            "image_name": f"{container_registry}/{name_as_snake_case}:latest",
            "owner_org": owner_org_key or "FIX-ME",
            "container_registry_profile": container_profile_key or "FIX-ME",
        }
    )
    config_path.write_text(json.dumps(content, indent=4))

    if git is True:
        # print("Initializing git repository...")
        subprocess.run(["git", "init"], cwd=path)
        subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True
        )
        rich.print(
            "You can now push your app to GitHub or another git provider. "
            "If using GitHub, try [blue]gh repo create[/blue] to create the repo in the CLI.\n"
            "If you want to push your app to a different git provider, or create the repository manually at github.com, you can add the repository like so:\n"
            "[blue]git remote add origin <url>[/blue]\n"
            "[blue]git push -u origin main[/blue]"
        )

    else:
        # if cicd is False:
        print("Removing CI/CD workflows")
        shutil.rmtree(path / ".github", ignore_errors=True)

    rich.print(
        "\n\nDone! You can now build your application with [blue]doover app build[/blue], run it with [blue]doover app run[/blue], or deploy it with [blue]doover app deploy[/blue].\n"
    )


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run(
    ctx: typer.Context,
    remote: typer.Argument(
        str,
        help="Remote host to run the application on. If not specified, runs locally.",
    ) = "localhost",
    port: int = 2375,
):
    """Runs an application. This assumes you have a docker-compose file in the `simulator` directory.

    This accepts additional arguments to pass to the `docker compose up` command.
    """
    root_fp = get_app_directory()

    print(f"Running application from {root_fp}")
    if not (root_fp / "simulators" / "docker-compose.yml").exists():
        raise FileNotFoundError(
            "docker-compose.yml not found. Please ensure there is a docker-compose.yml file in the simulators directory."
        )

    docker_path = get_docker_path()
    if remote:
        match = HOSTNAME_PATTERN.match(remote)
        if match:
            remote = f"{match.group('host') or 'doovit'}-{match.group('serial')}.local"

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((remote, port))
        except ConnectionRefusedError:
            typer.confirm(
                "Connection refused. Do you want me to try and disable the firewall?",
                default=True,
                abort=True,
            )

            try:
                from paramiko import SSHClient
            except ImportError:
                raise ImportError(
                    "paramiko not found. Please install it with uv add paramiko"
                )

            username = questionary.text(
                f"Please enter the username for {remote}:", default="doovit"
            ).ask()
            password = questionary.password(
                "Please enter the password (skip for SSH keys):",
                default="doovit",
            ).ask()

            client = SSHClient()
            client.load_system_host_keys()
            client.connect(remote, username=username, password=password)
            stdin, stdout, stderr = client.exec_command("dd dfw down")
            print(stdout.read().decode())
            print(stderr.read().decode())

        host_args = (f"--host={remote}:{port}",)
    else:
        host_args = ()

    # docker compose -f docker-compose.pump-aquamonix.yml up --build --abort-on-container-exit
    command = [
        str(docker_path),
        "docker",
        *host_args,
        "compose",
        "-f",
        str(root_fp / "simulators" / "docker-compose.yml"),
        "up",
        "--build",
        *ctx.args,
    ]
    rich.print(f"[green]Running: [/green]{' '.join(command)}")
    os.execl(*command)


@app.command()
def publish(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    skip_container: Annotated[
        bool,
        typer.Option(
            help="Whether to build and push the container image. Defaults to building and pushing."
        ),
    ] = False,
    staging: Annotated[
        bool,
        typer.Option(
            help="Whether to force staging mode. This defaults to working it out based on the API URL."
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Publish an application to Doover and its container registry.

    This pushes a built image to the app's docker registry and updates the application on the Doover site.
    """
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp)

    print(
        f"Updating application on doover site ({state.config_manager.current.base_url})...\n"
    )

    if staging is None:
        is_staging = ".d.doover" in state.api.base_url
    else:
        is_staging = staging

    key = app_config.staging_config.get("key") if is_staging else app_config.key

    try:
        if key is None:
            key = state.api.create_application(app_config, is_staging=is_staging)
            if is_staging:
                app_config.staging_config["key"] = key
            else:
                app_config.key = key

            app_config.save_to_disk()
            print(f"Created new application with key: {key}")
        else:
            state.api.update_application(app_config, is_staging=is_staging)
    except HTTPException as e:
        print(f"Failed to update application: {e}")
        raise typer.Exit(1)

    if app_config.build_args == "NO_BUILD":
        print("App requested to not build. Skipping build step.")
        print("Done!")
        raise typer.Exit(0)

    if skip_container is True:
        print("User requested to skip container build and push. Skipping...")
        print("Done!")
        raise typer.Exit(0)

    print("\nApp updated. Now pushing the image to the registry...\n")

    import docker

    client = docker.from_env()
    try:
        client.images.get(app_config.image_name)
    except ImageNotFound:
        typer.confirm(
            f"Image not found with name: {app_config.image_name}. Do you want me to build the image first?",
            abort=True,
        )

        shell_run(
            f"docker build {app_config.build_args} -t {app_config.image_name} {str(root_fp)}"
        )

    shell_run(f"docker push {app_config.image_name}")
    print("\n\nDone!")


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def build(
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
):
    """Build an application. Accepts additional arguments to pass to the `docker build` command.

    This uses the default `build_args` from the app config in the `doover_config.json` file.
    """
    root_fp = get_app_directory(app_fp)
    config = get_app_config(root_fp)

    if not config.image_name:
        print(
            "Image name not set in the configuration. Please set it in doover_config.json."
        )
        raise typer.Exit(1)

    shell_run(
        f"docker build {config.build_args} {' '.join(ctx.args)} -t {config.image_name} {str(root_fp)}",
    )


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def test(
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
):
    """Run tests on the application. This uses pytest and accepts any arguments to `pytest`."""
    root_fp = get_app_directory(app_fp)

    call_with_uv("pytest", str(root_fp), *ctx.args)


@app.command()
def lint(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    fix: Annotated[
        bool,
        typer.Option(help="The --fix option passed to ruff to fix linting failure."),
    ] = False,
):
    """Run linter on the application. This uses ruff and requires uv to be installed."""
    root_fp = get_app_directory(app_fp)
    args = ["ruff", "check", str(root_fp)]
    if fix:
        args.append("--fix")

    call_with_uv(*args)


@app.command(name="format")
def format_(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    fix: Annotated[
        bool,
        typer.Option(help="Make changes to fix formatting issues"),
    ] = False,
):
    """Run formatter on the application. This uses ruff and requires uv to be installed."""
    root_fp = get_app_directory(app_fp)
    args = ["ruff", "format", str(root_fp)]
    if fix is False:
        args.append("--check")

    call_with_uv(*args)


@app.command()
def channels(host: str = "localhost", port: int = 49100):
    """Open the channel viewer in your browser."""
    import webbrowser

    url = CHANNEL_VIEWER + "?" + urlencode({"local_url": f"http://{host}:{port}"})
    webbrowser.open(url)
