from typing import TYPE_CHECKING
import copy
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import time
from urllib.parse import urlencode
from pathlib import Path
from enum import Enum

import click
import jsonschema.exceptions
import rich
from pydoover.models.control import Application
from typing_extensions import Annotated

import requests
import typer
import questionary


from ..config_schema import export as export_config_command
from ..ui_schema import export as export_ui_command
from ..utils.api import ProfileAnnotation
from ..utils.apps import (
    get_app_directory,
    call_with_uv,
    get_docker_path,
    get_app_config,
)
from ..utils.crud import (
    build_update_command,
    parse_optional_bool,
    prompt_resource,
    resource_autocomplete,
)
from ..utils.prompt import QuestionaryPromptCommand
from ..utils.shell_commands import run as shell_run
from ..utils.sentry import capture_handled_exception
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase

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


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _control_base_url() -> str:
    session = getattr(state, "_session", None)
    if session is not None:
        return getattr(session.auth, "control_base_url", "") or ""

    try:
        return getattr(state.session.auth, "control_base_url", "") or ""
    except RuntimeError:
        return ""


def _resolve_staging(staging: bool | None) -> bool:
    if staging is not None:
        return staging
    return ".staging." in _control_base_url()


def _build_container(
    root_fp: Path, *, buildx: bool, build_args: str, image_name: str
) -> None:
    shell_run(
        f"docker {'buildx' if buildx else ''} build {build_args} -t {image_name} {str(root_fp)}",
    )


def _push_container(image_name: str) -> None:
    shell_run(f"docker push {image_name}")


def _require_publish_value(
    name: str, value, *, allow_empty_list: bool = False, allow_none: bool = False
):
    if value == "FIX-ME":
        raise typer.BadParameter(
            f"{name} is set to FIX-ME in doover_config.json. Update it before publishing."
        )
    if value is None and allow_none is False:
        raise typer.BadParameter(f"{name} is required in doover_config.json.")
    if isinstance(value, str) and not value.strip():
        raise typer.BadParameter(f"{name} is required in doover_config.json.")
    if allow_empty_list is False and isinstance(value, list) and not value:
        raise typer.BadParameter(f"{name} is required in doover_config.json.")
    return value


def _build_application_payload(
    app_config,
    *,
    staging: bool,
    include_deployment_data: bool,
) -> dict:
    payload = app_config.to_request_payload(
        include_deployment_data=include_deployment_data,
        is_staging=staging,
        method="POST",
    )

    _require_publish_value("name", payload["name"])
    _require_publish_value("display_name", payload["display_name"])
    _require_publish_value("description", payload["description"])
    _require_publish_value("type", payload["type"])
    _require_publish_value("visibility", payload["visibility"])
    _require_publish_value(
        "organisation_id", payload["organisation_id"], allow_none=True
    )
    _require_publish_value(
        "container_registry_profile_id",
        payload["container_registry_profile_id"],
        allow_none=True if payload["type"] != "DEV" else False,
    )
    _require_publish_value("depends_on", payload["depends_on"], allow_empty_list=True)

    if include_deployment_data is False:
        payload.pop("deployment_data", None)

    return {
        key: value
        for key, value in payload.items()
        if value is not None
        or key == "organisation_id"
        or key == "container_registry_profile_id"
    }


def _get_persisted_application_id(app_config, *, staging: bool) -> int | None:
    if staging:
        staging_id = getattr(app_config, "staging_config", {}).get("id")
        return int(staging_id) if staging_id is not None else None

    app_id = getattr(app_config, "id", None)
    return int(app_id) if app_id is not None else None


def _persist_application_id(app_config, *, staging: bool, application_id: int) -> None:
    if staging:
        app_config.staging_config["id"] = application_id
    else:
        app_config.id = application_id

    app_config.save_to_disk()


def _resolve_existing_application_id(
    client, app_config, *, staging: bool
) -> int | None:
    app_id = _get_persisted_application_id(app_config, staging=staging)
    if app_id is not None:
        return app_id

    page = client.applications.list(
        name=app_config.name,
        archived=False,
        page=1,
        per_page=100,
    )
    matches = [
        item for item in page.results if getattr(item, "name", None) == app_config.name
    ]
    if len(matches) > 1:
        raise typer.BadParameter(
            f"Multiple applications found matching name '{app_config.name}'. Set the application id in doover_config.json."
        )
    if len(matches) == 1:
        application_id = int(matches[0].id)
        _persist_application_id(
            app_config, staging=staging, application_id=application_id
        )
        return application_id
    return None


def _publish_processor_package(
    client,
    app_id: int,
    root_fp: Path,
) -> Application | None:
    package_fp = root_fp / "package.zip"
    if not package_fp.exists():
        raise FileNotFoundError(
            f"package.zip not found at {package_fp}. Ensure ./build.sh produced it."
        )

    return client.applications.processor_source(
        str(app_id),
        body={"file": package_fp},
    )


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
    ] = ContainerRegistry.GITHUB_INT,
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

    registry_name: str
    if container_registry is ContainerRegistry.GITHUB_OTHER:
        resp = questionary.text(
            "You selected an 'other' GitHub Packages registry. "
            "Please enter your GitHub organisation name, or GitHub username:"
        ).unsafe_ask()
        registry_name = f"ghcr.io/{resp}"
    elif container_registry is ContainerRegistry.DOCKERHUB_OTHER:
        registry_name = questionary.text(
            "You selected an 'other' DockerHub repository. "
            "Please enter the repository name (e.g spaneng):"
        ).unsafe_ask()
    elif container_registry is ContainerRegistry.DOCKERHUB_INT:
        registry_name = "spaneng"
    else:
        registry_name = container_registry.value
    registry_name = registry_name.strip()

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
            # git repos default to "main" rather than "latest" (dockerhub).
            "image_name": f"{registry_name}/{name_as_path}:{'main' if registry_name.startswith('ghcr') else 'latest'}",
            "owner_org_key": owner_org_key or "FIX-ME",
            "organisation_id": owner_org_key or "FIX-ME",
            "container_registry_profile_key": container_profile_key or "FIX-ME",
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
        "\n\nDone! You can now build your application with [blue]doover app build[/blue], run it with [blue]doover app run[/blue], or deploy it with [blue]doover app publish[/blue].\n"
    )


@app.command(name="list")
def list_(
    allow_many: Annotated[
        str | None,
        typer.Option(
            help="Filter by allow-many status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    approx_installs: Annotated[
        int | None, typer.Option(help="Filter by exact approximate installs value.")
    ] = None,
    approx_installs_gt: Annotated[
        int | None,
        typer.Option(
            "--approx-installs-gt",
            help="Filter by approximate installs greater than this value.",
        ),
    ] = None,
    approx_installs_gte: Annotated[
        int | None,
        typer.Option(
            "--approx-installs-gte",
            help="Filter by approximate installs greater than or equal to this value.",
        ),
    ] = None,
    approx_installs_lt: Annotated[
        int | None,
        typer.Option(
            "--approx-installs-lt",
            help="Filter by approximate installs less than this value.",
        ),
    ] = None,
    approx_installs_lte: Annotated[
        int | None,
        typer.Option(
            "--approx-installs-lte",
            help="Filter by approximate installs less than or equal to this value.",
        ),
    ] = None,
    archived: Annotated[
        str | None,
        typer.Option(
            help="Filter by archived status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    container_registry_profile: Annotated[
        str | None,
        typer.Option(help="Filter by container registry profile identifier."),
    ] = None,
    description: Annotated[
        str | None, typer.Option(help="Filter by exact description.")
    ] = None,
    description_contains: Annotated[
        str | None,
        typer.Option("--description-contains", help="Filter by description substring."),
    ] = None,
    description_icontains: Annotated[
        str | None,
        typer.Option(
            "--description-icontains",
            help="Filter by case-insensitive description substring.",
        ),
    ] = None,
    display_name: Annotated[
        str | None, typer.Option(help="Filter by exact display name.")
    ] = None,
    display_name_contains: Annotated[
        str | None,
        typer.Option(
            "--display-name-contains",
            help="Filter by display name substring.",
        ),
    ] = None,
    display_name_icontains: Annotated[
        str | None,
        typer.Option(
            "--display-name-icontains",
            help="Filter by case-insensitive display name substring.",
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by application ID.")] = None,
    name: Annotated[str | None, typer.Option(help="Filter by exact name.")] = None,
    name_contains: Annotated[
        str | None, typer.Option("--name-contains", help="Filter by name substring.")
    ] = None,
    name_icontains: Annotated[
        str | None,
        typer.Option(
            "--name-icontains",
            help="Filter by case-insensitive name substring.",
        ),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    organisation: Annotated[
        str | None, typer.Option(help="Filter by organisation identifier.")
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    stars: Annotated[
        int | None, typer.Option(help="Filter by exact stars value.")
    ] = None,
    stars_gt: Annotated[
        int | None,
        typer.Option("--stars-gt", help="Filter by stars greater than this value."),
    ] = None,
    stars_gte: Annotated[
        int | None,
        typer.Option(
            "--stars-gte",
            help="Filter by stars greater than or equal to this value.",
        ),
    ] = None,
    stars_lt: Annotated[
        int | None,
        typer.Option("--stars-lt", help="Filter by stars less than this value."),
    ] = None,
    stars_lte: Annotated[
        int | None,
        typer.Option(
            "--stars-lte",
            help="Filter by stars less than or equal to this value.",
        ),
    ] = None,
    type: Annotated[
        str | None, typer.Option(help="Filter by application type.")
    ] = None,
    visibility: Annotated[
        str | None, typer.Option(help="Filter by application visibility.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """List applications."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading applications..."):
        time.sleep(0.05)
        response = client.applications.list(
            allow_many=parse_optional_bool(allow_many, "--allow-many"),
            approx_installs=approx_installs,
            approx_installs__gt=approx_installs_gt,
            approx_installs__gte=approx_installs_gte,
            approx_installs__lt=approx_installs_lt,
            approx_installs__lte=approx_installs_lte,
            archived=parse_optional_bool(archived, "--archived"),
            container_registry_profile=container_registry_profile,
            description=description,
            description__contains=description_contains,
            description__icontains=description_icontains,
            display_name=display_name,
            display_name__contains=display_name_contains,
            display_name__icontains=display_name_icontains,
            id=id,
            name=name,
            name__contains=name_contains,
            name__icontains=name_icontains,
            ordering=ordering,
            organisation=organisation,
            page=page,
            per_page=per_page,
            search=search,
            stars=stars,
            stars__gt=stars_gt,
            stars__gte=stars_gte,
            stars__lt=stars_lt,
            stars__lte=stars_lte,
            type=type,
            visibility=visibility,
        )

    renderer.render_list(response)


@app.command()
def get(
    application_id: Annotated[
        str | None,
        typer.Argument(
            help="Application ID or exact name to retrieve.",
            autocompletion=resource_autocomplete(
                Application,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an application."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        Application,
        client,
        renderer,
        action="get",
        lookup=application_id,
        archived=False,
        ordering="name",
    )

    with renderer.loading("Loading application..."):
        response = client.applications.retrieve(str(resolved_id))

    renderer.render(response)


update = build_update_command(
    model_cls=Application,
    command_help="Update an application.",
    get_state=lambda: get_state(),
    resource_id_param_name="application_id",
    resource_id_help="Application ID or exact display name/name to update.",
)
app.command()(update)


@app.command()
def archive(
    application_id: Annotated[
        str | None,
        typer.Argument(
            help="Application ID or exact name to archive.",
            autocompletion=resource_autocomplete(
                Application,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive an application."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        Application,
        client,
        renderer,
        action="archive",
        lookup=application_id,
        archived=False,
        ordering="name",
    )

    with renderer.loading("Archiving application..."):
        response = client.applications.archive(str(resolved_id))

    renderer.render(response)


@app.command()
def unarchive(
    application_id: Annotated[
        str | None,
        typer.Argument(
            help="Application ID or exact name to unarchive.",
            autocompletion=resource_autocomplete(
                Application,
                archived=True,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive an application."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        Application,
        client,
        renderer,
        action="unarchive",
        lookup=application_id,
        archived=True,
        ordering="name",
    )

    with renderer.loading("Unarchiving application..."):
        response = client.applications.unarchive(str(resolved_id))

    renderer.render(response)


@app.command(name="put-widget")
def put_widget(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    widget_fp: Annotated[
        Path | None,
        typer.Option(
            help="Path to the widget file. Defaults to the widget path in doover_config.json."
        ),
    ] = None,
    app_name: Annotated[
        str | None,
        typer.Option(
            help="Application name in doover_config.json. Avoids prompting when multiple apps exist.",
        ),
    ] = None,
    staging: Annotated[
        bool | None,
        typer.Option(
            help="Whether to force staging mode. Defaults to working it out based on the API URL."
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Upload a widget file for an application."""
    _ = _profile
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp, app_name=app_name)
    client, renderer = get_state()

    resolved_staging = _resolve_staging(staging)
    application_id = _get_persisted_application_id(app_config, staging=resolved_staging)
    if application_id is None:
        rich.print(
            "[red]No application ID found in doover_config.json. Publish the app first.[/red]"
        )
        raise typer.Exit(1)

    if widget_fp is None:
        if app_config.widget_path is None:
            rich.print(
                "[red]No widget path provided and none found in doover_config.json.[/red]"
            )
            raise typer.Exit(1)
        widget_fp = app_config.widget_path

    if not widget_fp.exists():
        rich.print(f"[red]Widget file not found at {widget_fp}.[/red]")
        raise typer.Exit(1)

    with renderer.loading("Uploading widget..."):
        client.applications.widget(
            str(application_id),
            body={"file": widget_fp},
        )

    rich.print("[green]Widget uploaded successfully.[/green]")


@app.command(name="build-widget")
def build_widget(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    app_name: Annotated[
        str | None,
        typer.Option(
            help="Application name in doover_config.json. Avoids prompting when multiple apps exist.",
        ),
    ] = None,
):
    """Build the widget for an application.

    Runs the build_widget_command from doover_config.json, or defaults to `npm run build`.
    """
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp, app_name=app_name)
    command = app_config.build_widget_command or "npm run build"
    shell_run(command, cwd=root_fp)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run(
    ctx: typer.Context,
    remote: Annotated[
        str | None,
        typer.Argument(
            help="Remote host to run the application on. If not specified, runs locally.",
        ),
    ] = None,
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

        # os.execl will use the current env so let's just set DOCKER_HOST here.
        os.environ["DOCKER_HOST"] = f"{remote}:{port}"
        rich.print(
            f"[green]Environment variable set: [/green]DOCKER_HOST={os.environ['DOCKER_HOST']}"
        )

    # docker compose -f docker-compose.pump-aquamonix.yml up --build --abort-on-container-exit
    command = [
        str(docker_path),
        "docker",
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
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    build_container: Annotated[
        bool,
        typer.Option(
            help="Build and push the container image to the registry."
        ),
    ] = False,
    staging: Annotated[
        bool | None,
        typer.Option(
            help="Whether to force staging mode. This defaults to working it out based on the API URL."
        ),
    ] = None,
    export_config: Annotated[
        bool,
        typer.Option(
            help="Export the application configuration before publishing.",
        ),
    ] = True,
    export_ui: Annotated[
        bool,
        typer.Option(
            help="Export the application UI schema before publishing.",
        ),
    ] = True,
    build_widget: Annotated[
        bool,
        typer.Option(
            help="Build the widget before publishing. Disable with --no-build-widget.",
        ),
    ] = True,
    put_widget: Annotated[
        bool,
        typer.Option(
            help="Upload the widget when publishing. Disable with --no-put-widget.",
        ),
    ] = True,
    app_name: Annotated[
        str | None,
        typer.Option(
            help="Application name in doover_config.json. Avoids prompting when multiple apps exist.",
        ),
    ] = None,
    buildx: Annotated[
        bool,
        typer.Option(
            help="Use docker buildx to build the application. This is useful for multi-platform builds.",
        ),
    ] = True,
    _profile: ProfileAnnotation = None,
):
    """Publish an application to Doover and its container registry.

    This pushes a built image to the app's docker registry and updates the application on the Doover site.
    """
    _ = _profile
    root_fp = get_app_directory(app_fp)

    # Resolve the app name early so subsequent get_app_config calls don't re-prompt.
    _ = get_app_config(root_fp, app_name=app_name)

    if export_config:
        try:
            ctx.invoke(export_config_command, ctx, app_fp=root_fp, validate_=True)
        except jsonschema.exceptions.SchemaError as exc:
            summary, remainder = str(exc).split("\n", 1)
            rich.print(
                f"[red]Failed to export application configuration: {summary}[/red]\n{remainder}\n"
            )
            typer.confirm("Do you want to continue?", abort=True)
        else:
            rich.print("[green]Exported application configuration.[/green]")

    if export_ui:
        try:
            ctx.invoke(export_ui_command, ctx, app_fp=root_fp, validate_=True)
        except Exception as exc:
            rich.print(f"[red]Failed to export UI schema: {exc}[/red]\n")
            typer.confirm("Do you want to continue?", abort=True)
        else:
            rich.print("[green]Exported UI schema.[/green]")

    app_config = get_app_config(root_fp)
    resolved_staging = _resolve_staging(staging)
    payload = _build_application_payload(
        app_config,
        staging=resolved_staging,
        include_deployment_data=True,
    )

    client, renderer = get_state()

    rich.print(
        f"Updating application on doover site ({_control_base_url() or 'unknown base URL'})...\n"
    )

    try:
        with renderer.loading("Publishing application..."):
            # application_id = _resolve_existing_application_id(
            #     client,
            #     app_config,
            #     staging=resolved_staging,
            # )
            application_id = _get_persisted_application_id(
                app_config, staging=resolved_staging
            )
            if application_id is None:
                print(json.dumps(payload, indent=4))
                created = client.applications.create(body=dict(payload))
                application_id = int(created.id)
                _persist_application_id(
                    app_config,
                    staging=resolved_staging,
                    application_id=application_id,
                )
                print(f"Created new application with id: {application_id}")

            response = client.applications.partial(
                str(application_id),
                body=dict(payload),
            )
    except typer.Exit:
        raise
    except click.Abort:
        raise
    except Exception as exc:
        print(f"Failed to update application: {exc}")
        capture_handled_exception(
            exc,
            command="app.publish",
            message=f"Failed to update application: {exc}",
        )
        raise typer.Exit(1) from exc

    if app_config.widget_path is not None:
        if build_widget:
            build_cmd = app_config.build_widget_command or "npm run build"
            rich.print(f"\nBuilding widget with: [blue]{build_cmd}[/blue]")
            shell_run(build_cmd, cwd=root_fp)

        if put_widget:
            if not app_config.widget_path.exists():
                rich.print(
                    f"[red]Widget file not found at {app_config.widget_path}.[/red]"
                )
                raise typer.Exit(1)

            with renderer.loading("Uploading widget..."):
                client.applications.widget(
                    str(application_id),
                    body={"file": app_config.widget_path},
                )
            rich.print("[green]Widget uploaded.[/green]")

    if app_config.type in ("PRO", "REP", "INT"):
        print("\nBuilding package.zip for upload...")
        shell_run("./build.sh", cwd=root_fp)
        print("Uploading package.zip to Doover...")
        processor_response = _publish_processor_package(
            client,
            application_id,
            root_fp,
        )
        print("Done!")

        print("Creating new lambda version release...")
        version_response = client.applications.processor_version(
            str(application_id),
            body=dict(payload),
        )
        print("Done!")
        renderer.render(version_response or processor_response or response)
        raise typer.Exit(0)

    if build_container:
        image_name = _require_publish_value("image_name", payload.get("image_name"))
        build_args = getattr(app_config, "build_args", "") or ""
        if build_args != "NO_BUILD":
            print("\nBuilding and pushing container image to the registry...")
            _build_container(
                root_fp,
                buildx=buildx,
                build_args=build_args,
                image_name=image_name,
            )
            _push_container(image_name)
        else:
            print("App requested to not build. Skipping build step.")

    print("\n\nDone!")
    renderer.render(response)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def build(
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    buildx: Annotated[
        bool,
        typer.Option(
            help="Use docker buildx to build the application. This is useful for multi-platform builds.",
        ),
    ] = True,
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

    _build_container(
        root_fp,
        buildx=buildx,
        build_args=f"{config.build_args} {' '.join(ctx.args)}".strip(),
        image_name=config.image_name,
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
