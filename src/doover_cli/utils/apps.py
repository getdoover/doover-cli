import os
import json
import base64
import shutil
from pathlib import Path
from typing import Any

import typer
import questionary
from pydoover.models.control import Application as ControlApplication

from .shell_commands import run


def get_id_or_key(data: dict[str, Any], key: str) -> Any:
    try:
        return data[f"{key}_id"]
    except KeyError:
        return data.get(key)


class LocalApplication(ControlApplication):
    _model_name = None

    def __init__(
        self,
        *,
        id: int | None = None,
        archived: bool | None = None,
        name: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        long_description: str | Path | None = None,
        type: str | None = None,
        visibility: str | None = None,
        allow_many: bool | None = None,
        config_schema: Any | None = None,
        ui_schema: Any | None = None,
        depends_on: list[str] | None = None,
        organisation: dict[str, Any] | str | int | None = None,
        approx_installs: int | None = None,
        stars: int | None = None,
        container_registry_profile: dict[str, Any] | str | int | None = None,
        deployment_data: str | None = None,
        image_name: str | None = None,
        lambda_arn: str | None = None,
        lambda_config: Any | None = None,
        config_profiles: list[Any] | None = None,
        icon_url: str | None = None,
        banner_url: str | None = None,
        key: str | None = None,
        code_repo_id: str | int | None = None,
        repo_branch: str | None = None,
        build_args: str | None = None,
        widget: str | Path | None = None,
        build_widget_command: str | None = None,
        export_config_command: str | None = None,
        export_ui_command: str | None = None,
        run_command: str | None = None,
        staging_config: dict[str, Any] | None = None,
        base_path: Path | None = None,
        deployment_folder: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            archived=archived,
            name=name,
            display_name=display_name,
            description=description,
            long_description="",
            type=type,
            visibility=visibility,
            allow_many=allow_many,
            config_schema=config_schema,
            ui_schema=ui_schema,
            depends_on=depends_on,
            organisation=organisation,
            approx_installs=approx_installs,
            stars=stars,
            container_registry_profile=container_registry_profile,
            deployment_data=deployment_data,
            image_name=image_name,
            lambda_arn=lambda_arn,
            lambda_config=lambda_config,
            config_profiles=config_profiles,
            icon_url=icon_url,
            banner_url=banner_url,
        )

        path = (
            base_path / long_description
            if isinstance(base_path, Path) and isinstance(long_description, str)
            else long_description
        )
        if isinstance(path, Path) and path.exists():
            self.long_description = path.read_text()
        else:
            self.long_description = str(long_description or "")

        self._widget_raw = str(widget) if widget else None
        if widget is not None:
            widget_path = Path(widget)
            if not widget_path.is_absolute() and base_path is not None:
                widget_path = base_path / widget_path
            self.widget_path: Path | None = widget_path
        else:
            self.widget_path = None

        self.build_widget_command = build_widget_command
        self.key = key
        self.code_repo_id = code_repo_id
        self.repo_branch = repo_branch or "main"
        self.build_args = build_args
        self.export_config_command = export_config_command
        self.export_ui_command = export_ui_command
        self.run_command = run_command
        self.staging_config = staging_config or {}
        self.base_path = base_path
        self.deployment_folder = deployment_folder or "deployment"

    @property
    def src_directory(self) -> Path:
        return (self.base_path or Path()) / "src" / (self.name or "").replace("-", "_")

    @staticmethod
    def _request_payload_keys() -> set[str]:
        fields = ControlApplication._versions["ApplicationSerializerDetailRequest"][
            "fields"
        ]
        keys = set()
        for field_name, config in fields.items():
            keys.add(config.get("output_id", field_name))
        return keys

    def _deployment_data(self) -> str | None:
        deployment_fp = (self.base_path or Path()) / self.deployment_folder
        if not deployment_fp.exists():
            return None

        tmp_fp = Path(f"/tmp/{self.name}_deployment_data.zip")
        shutil.make_archive(str(tmp_fp.with_suffix("")), "zip", deployment_fp)
        return base64.b64encode(tmp_fp.read_bytes()).decode("utf-8")

    @classmethod
    def from_config(cls, data: dict[str, Any], app_base: Path) -> "LocalApplication":
        return cls(
            id=data.get("id"),
            key=data.get("key"),
            name=data.get("name"),
            display_name=data.get("display_name"),
            type=data.get("type"),
            visibility=data.get("visibility"),
            allow_many=data.get("allow_many", False),
            description=data.get("description"),
            long_description=data.get("long_description"),
            depends_on=list(data.get("depends_on", [])),
            organisation=get_id_or_key(data, "owner_org")
            or get_id_or_key(data, "organisation"),
            code_repo_id=get_id_or_key(data, "code_repo"),
            repo_branch=data.get("repo_branch"),
            image_name=data.get("image_name"),
            build_args=data.get("build_args"),
            container_registry_profile=get_id_or_key(
                data,
                "container_registry_profile",
            ),
            lambda_arn=data.get("lambda_arn"),
            lambda_config=data.get("lambda_config"),
            widget=data.get("widget"),
            build_widget_command=data.get("build_widget_command"),
            export_config_command=data.get("export_config_command"),
            export_ui_command=data.get("export_ui_command"),
            run_command=data.get("run_command"),
            config_schema=data.get("config_schema"),
            ui_schema=data.get("ui_schema"),
            staging_config=data.get("staging_config", {}),
            icon_url=data.get("icon_url"),
            banner_url=data.get("banner_url"),
            base_path=app_base,
            deployment_folder=data.get("deployment_folder"),
        )

    def to_request_payload(
        self,
        *,
        include_deployment_data: bool = False,
        is_staging: bool = False,
        method: str = "POST",
    ) -> dict[str, Any]:
        payload = self.to_version("ApplicationSerializerDetailRequest", method=method)
        if is_staging:
            payload.update(
                {
                    key: value
                    for key, value in self.staging_config.items()
                    if key in self._request_payload_keys()
                }
            )

        if include_deployment_data:
            payload["deployment_data"] = self._deployment_data()

        return payload

    def to_config_dict(
        self,
        include_deployment_data: bool = False,
        is_staging: bool = False,
        include_cloud_only: bool = False,
    ) -> dict[str, Any]:
        data = self.to_request_payload(
            include_deployment_data=include_deployment_data,
            is_staging=is_staging,
            method="POST",
        )
        data.update(
            {
                "id": self.id,
                "key": self.key,
                "owner_org_id": data.get("organisation_id"),
                "code_repo_id": self.code_repo_id,
                "repo_branch": self.repo_branch,
                "build_args": self.build_args,
                "image_name": self.image_name,
                "lambda_config": self.lambda_config,
                "config_schema": self.config_schema,
                "ui_schema": self.ui_schema,
                "icon_url": self.icon_url,
                "banner_url": self.banner_url,
            }
        )

        if self._widget_raw is not None:
            data["widget"] = self._widget_raw

        if self.deployment_folder != "deployment":
            data["deployment_folder"] = self.deployment_folder

        if include_deployment_data is False:
            data["staging_config"] = self.staging_config
            data["build_widget_command"] = self.build_widget_command
            data["export_config_command"] = self.export_config_command
            data["export_ui_command"] = self.export_ui_command
            data["run_command"] = self.run_command

        if include_cloud_only:
            data["lambda_arn"] = self.lambda_arn

        return data

    def to_dict(
        self,
        include_deployment_data: bool = False,
        is_staging: bool = False,
        include_cloud_only: bool = False,
    ) -> dict[str, Any]:
        return self.to_config_dict(
            include_deployment_data=include_deployment_data,
            is_staging=is_staging,
            include_cloud_only=include_cloud_only,
        )

    def save_to_disk(self) -> None:
        if self.base_path is None:
            raise ValueError("Application base path is not set.")

        config_path = self.base_path / "doover_config.json"
        app_name = self.name or ""
        data: dict[str, dict[str, Any]] = (
            dict(json.loads(config_path.read_text()))
            if config_path.exists()
            else {app_name: {}}
        )

        upstream = self.to_config_dict(include_cloud_only=True)
        upstream.pop("long_description", None)

        data.setdefault(app_name, {}).update(**upstream)
        config_path.write_text(json.dumps(data, indent=4))


def get_app_directory(root: Path | None = None) -> Path:
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


def call_with_uv(
    *args,
    uv_run: bool = True,
    in_shell: bool = False,
    cwd: Path | None = None,
):
    uv_path = get_uv_path()
    if uv_run:
        args = ["uv", "run"] + list(args)

    if in_shell:
        run(" ".join(str(r) for r in args), cwd=cwd)
    else:
        if cwd:
            os.chdir(cwd)
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


_selected_app_name: dict[Path, str] = {}


def get_app_config(root_fp: Path, app_name: str | None = None) -> Any:
    config_path = root_fp / "doover_config.json"
    if not config_path.exists():
        print(f"Configuration file not found at {config_path}.")
        raise typer.Exit(1)

    with open(config_path, "r") as file:
        data = json.load(file)

    result = []
    for k, v in data.items():
        if isinstance(v, dict) and "config_schema" in v:
            # config_schema bit of a prerequisite for an app config entry.
            result.append(LocalApplication.from_config(v, root_fp))

    if len(result) == 0:
        print(
            f"No application configuration found in the `doover_config.json` file at {root_fp}. "
            f"Make sure the `type` is set to `application` in the configuration."
        )
        raise typer.Exit(1)
    elif len(result) == 1:
        return result[0]

    lookup = {r.name: r for r in result}

    # Use explicit app_name, then cached selection, then prompt.
    resolved = root_fp.resolve()
    name = app_name or _selected_app_name.get(resolved)
    if name and name in lookup:
        return lookup[name]

    choice = questionary.select(
        "Multiple application configurations found. Please select one:",
        choices=list(lookup.keys()),
    ).ask()
    _selected_app_name[resolved] = choice
    return lookup[choice]
