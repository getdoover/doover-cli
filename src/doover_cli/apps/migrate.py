"""Bring an app repository onto the current doover_config.json / CI format.

Several things changed at once and every app repo has to make all the moves, so
they live in one command rather than several:

  * images come from the Doover registry, whose reference is derived from the app
    name rather than hand-written per repo;
  * config and UI schemas are generated from the Python/Rust at publish time, so
    the copies committed into doover_config.json are stale duplicates of the real
    source of truth;
  * the per-repo build/lint/test workflows are replaced by the shared reusable
    workflow in getdoover/workflows;
  * a widget's ConcatenatePlugin.ts is vendored per repo rather than installed,
    so a fix to it only reaches the fleet by being copied in.

The rewrite is deliberately conservative: it drops keys that provably do nothing
and rewrites the ones that must change, and leaves everything else -- including
anything it doesn't recognise -- exactly where it found it.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import rich
import typer
from typing_extensions import Annotated

from ..registry import DEFAULT_REGISTRY
from ..utils.apps import (
    DEPRECATED_REFS,
    RETIRED_FIELDS,
    LocalApplication,
    _config_paths,
)
from ..utils.state import state
from .widget_plugin import PLUGIN_SOURCE, plan_widget_plugins

# Every image on a Doover registry lives under this namespace, so the reference
# is `<registry>/apps/<app name>:<tag>` and nothing about it needs to be
# hand-written per repo. One reference covers both environments: staging pulls
# the same image production does, so nothing rebuilds between them and the digest
# released to each is identical.
REGISTRY_NAMESPACE = "apps"
DEFAULT_IMAGE_TAG = "main"

# The Doover-internal container registry profile, per environment. Deleting
# `container_registry_profile_id` from doover_config.json only stops the repo
# asserting it -- whatever the cloud already holds stays until something patches
# it, so the migration does that itself. Keyed by whether the control plane is
# staging.
REGISTRY_PROFILE_IDS = {
    False: 207438204347877900,
    True: 207438400544835590,
}

# Generated from the app's Python/Rust at publish time. A committed copy is a
# stale duplicate that nothing reads.
GENERATED_FIELDS = ("config_schema", "ui_schema")

# Container registry credentials are minted by the control plane against the
# app's publish permission now, so a registry profile no longer selects
# anything. `handler` is a top-level copy of `lambda_config.Handler` that a
# couple of processor configs grew; nothing has ever read it.
OBSOLETE_FIELDS = (
    "container_registry_profile_id",
    "container_registry_profile",
    "handler",
)

# Optional fields worth keeping when they hold a value, but pure noise when
# null: their absence and their null mean the same thing to the control plane.
# `organisation_id` is deliberately not here -- an explicit null clears the
# owning org, which is a real instruction.
DROP_WHEN_NULL = (
    "key",
    "image_name",
    "build_args",
    "icon_url",
    "banner_url",
    "lambda_config",
    "build_widget_command",
    "export_config_command",
    "export_ui_command",
    "run_command",
    "widget",
    "deployment_folder",
)

# The order a migrated entry is written in: identity, then description, then
# deployment. Purely cosmetic, but it makes diffs between app repos readable.
KEY_ORDER = (
    "id",
    "name",
    "display_name",
    "type",
    "visibility",
    "allow_many",
    "description",
    "long_description",
    "icon_url",
    "banner_url",
    "depends_on",
    "organisation_id",
    "image_name",
    "build_args",
    "widget",
    "build_widget_command",
    "export_config_command",
    "export_ui_command",
    "run_command",
    "deployment_folder",
    "lambda_config",
    "staging_config",
)

STAGING_KEEP = ("id",)

# Workflows the shared one replaces. Matched by name *and* content, so a repo
# that happens to have an unrelated `run-tests.yml` keeps it.
LEGACY_WORKFLOWS = (
    "build-image.yml",
    # The hand-rolled processor release workflow. Only replaceable now that the
    # shared workflow publishes package apps as well as images.
    "deploy.yml",
    "build_image.yml",
    "lint-and-test.yml",
    "run-linting.yml",
    "run-lint.yml",
    "run-tests.yml",
    "validate-schema.yml",
    "doover-app.yml",
)

# Something only a doover app workflow says. Any one of these in a file named
# above is enough to call it ours to delete.
LEGACY_WORKFLOW_MARKERS = (
    "doover",
    "DOOVER_APP_NAME",
    "spaneng/doover_device_base",
    # The lint/test/build trio the shared workflow replaces: they either call
    # each other as local reusable workflows, or run the steps directly.
    "./.github/workflows/run-",
    "ruff",
    "pytest",
    "docker/build-push-action",
)

WORKFLOW_NAME = "doover-app.yml"
DEFAULT_WORKFLOW_REF = "getdoover/workflows/.github/workflows/app.yml@main"

WORKFLOW_TEMPLATE = """\
name: Doover App

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  id-token: write

jobs:
  app:
    uses: {ref}
    secrets: inherit
"""


def _split_image(image_name: str | None) -> tuple[str | None, str]:
    """The repository and tag of an image reference.

    Splitting on the last colon is only safe once the (optional) registry port
    is out of the way, hence the slash check.
    """
    if not image_name:
        return None, DEFAULT_IMAGE_TAG
    repository, _, tag = image_name.rpartition(":")
    if not repository or "/" in tag:
        return image_name, DEFAULT_IMAGE_TAG
    return repository, tag or DEFAULT_IMAGE_TAG


def registry_image(name: str, registry: str, tag: str = DEFAULT_IMAGE_TAG) -> str:
    return f"{registry}/{REGISTRY_NAMESPACE}/{name}:{tag}"


def _migrate_image_name(entry: dict[str, Any], name: str) -> str | None:
    """The Doover-registry reference for this app, or None to leave it alone.

    An app that has no image at all (a processor, or one that deploys an
    off-the-shelf image) keeps whatever it has: only a reference this repo owns
    is rewritten.
    """
    current = entry.get("image_name")
    if not current:
        return None

    _, tag = _split_image(current)
    return registry_image(name, DEFAULT_REGISTRY, tag)


def _migrate_staging(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The staging override, reduced to the one thing it still says.

    Staging is a separate control plane with its own application ids, so a pinned
    staging id is the only field that means anything here. The image is
    deliberately not overridden: both environments run the same reference, so a
    staging-specific `image_name` would fork the two apart. Everything else a
    staging_config used to carry was a copy of the production entry.
    """
    staging = entry.get("staging_config")
    if not isinstance(staging, dict):
        return None

    migrated = {
        key: staging[key] for key in STAGING_KEEP if staging.get(key) is not None
    }
    return migrated or None


def migrate_entry(entry: dict[str, Any], key: str) -> dict[str, Any]:
    """One app entry from doover_config.json, in the current format."""
    migrated = dict(entry)
    name = migrated.get("name") or key
    migrated["name"] = name

    # Legacy spellings first, so the canonical key exists before ordering. The
    # canonical one wins where a config carries both.
    for legacy, canonical in DEPRECATED_REFS.items():
        if legacy in migrated:
            value = migrated.pop(legacy)
            migrated.setdefault(canonical, value)

    for field in (*RETIRED_FIELDS, *GENERATED_FIELDS, *OBSOLETE_FIELDS):
        migrated.pop(field, None)

    image_name = _migrate_image_name(migrated, name)
    if image_name is not None:
        migrated["image_name"] = image_name

    staging = _migrate_staging(migrated)
    if staging is None:
        migrated.pop("staging_config", None)
    else:
        migrated["staging_config"] = staging

    for field in DROP_WHEN_NULL:
        if migrated.get(field) is None:
            migrated.pop(field, None)

    ordered = {k: migrated.pop(k) for k in KEY_ORDER if k in migrated}
    # Anything unrecognised keeps its value and goes last, rather than being
    # dropped for not being on a list this command happens to know about.
    ordered.update(migrated)
    return ordered


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """A whole doover_config.json. Non-app entries pass through untouched."""
    return {
        key: migrate_entry(value, key)
        if isinstance(value, dict) and "type" in value
        else value
        for key, value in data.items()
    }


# `image:` in a compose file, captured so the reference can be swapped without
# reformatting the line around it. Compose files are edited as text rather than
# round-tripped through a YAML dump, which would lose comments and ordering.
#
# The closing quote is matched by backreference rather than swept into `suffix`,
# which is what the line is rebuilt from: leaving it there and re-adding the
# opening quote emitted a doubled quote and broke every quoted image line.
_COMPOSE_IMAGE = re.compile(
    r"^(?P<prefix>\s*image:\s*)(?P<quote>['\"]?)(?P<ref>[^'\"\s#]+)"
    r"(?P=quote)(?P<suffix>.*)$"
)


def image_key(reference: str) -> str:
    """The app an image reference names, ignoring registry, namespace and tag.

    `spaneng/host-configurator:main` and
    `registry.doover.com/apps/host_configurator:main` are the same app under two
    registries, so both reduce to `host_configurator`. Hyphens fold to
    underscores because image names use one and app names the other.
    """
    repository, _ = _split_image(reference)
    return (repository or "").rsplit("/", 1)[-1].replace("-", "_").lower()


def _explicit_tag(reference: str) -> str | None:
    """The tag a reference actually spells out, or None if it leans on a default.

    Distinguished from `_split_image`, which substitutes a default, because a
    tag someone wrote by hand is a deliberate choice about *which artifact* --
    and the two cases want opposite answers when the compose file and the config
    disagree.
    """
    repository, separator, tag = reference.rpartition(":")
    if not separator or not repository or "/" in tag:
        return None
    return tag or None


# What a rendered deployment substitutes for the app's own image. A template
# that says this needs no migration ever again: each app in a multi-app repo
# renders its own `image_name`, which one hard-coded reference cannot do.
IMAGE_PLACEHOLDER = "{{ IMAGE_NAME }}"


def _is_jinja(path: Path, content: str) -> bool:
    """Whether this deployment file is rendered before a device sees it.

    Two signals, either sufficient: a suffix past the `.yml` (`.yml.template`,
    `.yaml.j2`), and delimiters already in the body. Only a rendered file can
    carry `{{ IMAGE_NAME }}`; writing it into a plain compose file would pin the
    device to an image called `{{`.
    """
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes and suffixes[-1] not in (".yml", ".yaml"):
        return True
    return "{{" in content or "{%" in content


def migrate_compose(content: str, images: dict[str, str], jinja: bool = False) -> str:
    """A compose file with each app's image pointed at its registered reference.

    `images` maps `image_key` to the `image_name` doover_config.json now
    declares. An image that matches no app in this repo -- a sidecar, a
    third-party service -- is left exactly as it is.

    A `jinja` file gets `{{ IMAGE_NAME }}` rather than the reference itself.
    That is the difference between a repo that migrates once and a repo that
    needs migrating again at every registry move -- and it is the only correct
    answer where several apps share one compose file, since the literal can only
    ever name one of them. Anything else gets the literal reference.

    Only the repository moves: a tag the compose file spells out is kept. Apps
    ship sidecars built from their own repository under a different tag --
    device-compliance runs `device-compliance:dnsmasq` beside
    `device-compliance:main` -- and those differ from the app only by tag, so
    taking the registered reference wholesale replaced the sidecar with a second
    copy of the app.
    """
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = _COMPOSE_IMAGE.match(line.rstrip("\n"))
        if match is None:
            continue
        registered = images.get(image_key(match["ref"]))
        if registered is None:
            continue
        if jinja:
            replacement = IMAGE_PLACEHOLDER
        else:
            repository, registered_tag = _split_image(registered)
            tag = _explicit_tag(match["ref"]) or registered_tag
            replacement = f"{repository}:{tag}"
        if replacement == match["ref"]:
            continue
        newline = "\n" if line.endswith("\n") else ""
        lines[index] = (
            f"{match['prefix']}{match['quote']}{replacement}"
            f"{match['quote']}{match['suffix']}{newline}"
        )
    return "".join(lines)


def _compose_paths(app_dir: Path, entry: dict[str, Any]) -> list[Path]:
    """The deployment files an app ships, which are what actually run on a device.

    `deployment_data` is built from this folder and published alongside the app,
    so an image pinned here is the one the device pulls -- regardless of what
    `image_name` says. That is how a repo ends up migrated but still deploying a
    stale image.

    Matched on any `.yml`/`.yaml` in the name rather than the final suffix,
    because the files that most need rewriting are the rendered ones --
    `docker-compose.yml.template` is the fleet's second most common deployment
    file, and matching on `path.suffix` skipped every one of them.
    """
    folder = app_dir / (entry.get("deployment_folder") or "deployment")
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and any(suffix.lower() in (".yml", ".yaml") for suffix in path.suffixes)
    )


# `npm run build`, with or without a --prefix. Deliberately narrow: only a plain
# build command is rewritten, because anything else is a command someone wrote on
# purpose and may already install by another route.
_NPM_BUILD = re.compile(
    r"^npm(?P<prefix>\s+--prefix\s+(?P<dir>\S+))?\s+run\s+build\s*$"
)


def widget_build_command(command: str | None) -> str | None:
    """`command` with a dependency install in front of it, or None to leave it.

    A widget build runs on a fresh runner where `node_modules` does not exist, so
    `npm run build` fails on the build tool itself being absent -- rsbuild, in the
    case that surfaced this. The install belongs in the command rather than being
    hardcoded around it: an app that installs some other way keeps working, and
    the command in doover_config.json stays the whole truth about how the widget
    is built.

    `npm install` rather than `npm ci`: the same command runs on a developer's
    machine via `doover app build-widget`, where `ci` deleting and refetching
    node_modules on every build is a poor trade for reproducibility, and it fails
    outright in a repo with no committed lockfile.
    """
    if not command:
        return None

    match = _NPM_BUILD.match(command.strip())
    if match is None:
        # Already installs, or does something this doesn't understand.
        return None

    prefix = match["prefix"] or ""
    return f"npm{prefix} install && {command.strip()}"


def _apply_widget_install(data: dict[str, Any]) -> None:
    for entry in data.values():
        if not (isinstance(entry, dict) and "type" in entry):
            continue
        updated = widget_build_command(entry.get("build_widget_command"))
        if updated is not None:
            entry["build_widget_command"] = updated


def _is_legacy_workflow(path: Path) -> bool:
    if path.name not in LEGACY_WORKFLOWS:
        return False
    try:
        content = path.read_text()
    except OSError:
        return False
    return any(marker in content for marker in LEGACY_WORKFLOW_MARKERS)


def _still_referenced(path: Path, survivors: list[Path]) -> bool:
    """Whether a workflow that is staying calls `path` as a reusable workflow.

    The legacy lint/test/schema workflows were called by whatever sat above them,
    so deleting one out from under a caller that survives -- a repo's own
    processor release workflow, say -- breaks that workflow rather than
    retiring it.
    """
    reference = f"./.github/workflows/{path.name}"
    for other in survivors:
        try:
            if reference in other.read_text():
                return True
        except OSError:
            continue
    return False


def _plan_workflows(root: Path, ref: str) -> tuple[list[Path], Path | None, str]:
    """Which workflow files to delete, and the shared one to write.

    Returns `(delete, write_path, content)`; `write_path` is None when the repo
    already has exactly the workflow this would write.
    """
    workflows_dir = root / ".github" / "workflows"
    content = WORKFLOW_TEMPLATE.format(ref=ref)
    target = workflows_dir / WORKFLOW_NAME

    delete: list[Path] = []
    if workflows_dir.is_dir():
        existing = sorted(p for p in workflows_dir.iterdir() if p.is_file())
        candidates = [p for p in existing if _is_legacy_workflow(p)]
        survivors = [p for p in existing if p not in candidates]
        delete = [p for p in candidates if not _still_referenced(p, survivors)]

    if target.exists() and target.read_text() == content:
        # Already migrated -- don't rewrite the file, and don't delete it either.
        return [p for p in delete if p != target], None, content

    return delete, target, content


# Trusted publishing: the control plane trusts a (repository, workflow) pair to
# publish an application, and each application points at the publisher allowed to
# release it. Matching is on the workflow's *filename*, so this has to be the file
# the migration writes.
PUBLISHERS_PATH = "/publishers/"
GITHUB_PROVIDER = "GH"

_GITHUB_REMOTE = re.compile(
    r"^(?:https://|git@|ssh://git@)github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)


def _github_repository(root: Path) -> tuple[str, str] | None:
    """The GitHub `(owner, name)` this repo pushes to, or None.

    Read from the git remote rather than asked for: the answer is already in the
    checkout, and a migration that prompts cannot be run over a fleet of repos.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None

    match = _GITHUB_REMOTE.match(result.stdout.strip())
    if match is None:
        return None
    return match["owner"], match["name"]


def _publisher_request(
    session,
    method: str,
    *,
    publisher_id: Any | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    organisation_id: int | None = None,
) -> Any:
    """Call the control plane's `/publishers/` endpoint.

    Spoken to over plain HTTP because pydoover has no generated `publishers`
    group yet -- the OpenAPI spec it generates from predates the endpoint. Only
    the auth client's public surface is used (`ensure_token`, `get_auth_headers`,
    `control_base_url`), no pydoover internals, so this collapses into
    `client.publishers.…` the moment those bindings exist.
    """
    import httpx

    auth = session.auth
    auth.ensure_token()
    headers = dict(auth.get_auth_headers())
    if organisation_id is not None:
        headers["X-Doover-Organisation"] = str(organisation_id)

    url = auth.control_base_url.rstrip("/") + PUBLISHERS_PATH
    if publisher_id is not None:
        url += f"{publisher_id}/"
    response = httpx.request(
        method, url, headers=headers, params=params, json=body, timeout=60
    )
    response.raise_for_status()
    return response.json() if response.content else None


def _repo_publishers(
    session, owner: str, name: str, organisation_id: int | None
) -> list[dict[str, Any]]:
    payload = _publisher_request(session, "GET", organisation_id=organisation_id)
    results = payload.get("results", []) if isinstance(payload, dict) else payload or []
    return [
        publisher
        for publisher in results
        if publisher.get("provider") == GITHUB_PROVIDER
        and publisher.get("repository_owner") == owner
        and publisher.get("repository_name") == name
    ]


def _publisher_workflow(publisher: dict[str, Any]) -> str:
    # The OIDC claim carries a path; the control plane matches on the basename.
    return Path(publisher.get("workflow") or "").name


def _ensure_publisher(
    session,
    owner: str,
    name: str,
    workflow: str,
    organisation_id: int | None,
    *,
    root: Path,
) -> tuple[Any, str]:
    """The publisher trusted to publish this repo through `workflow`.

    Returns `(id, action)`, where action is "found", "renamed" or "created".

    Renaming matters because migrating a repo renames its workflow file, and a
    publisher is matched on that filename: leaving the old row behind would
    orphan the trust for every app pointing at it and create a second row saying
    the same thing. So a publisher of this repo whose workflow file the migration
    has just deleted is moved to the new name -- but only when it is the only such
    row, since a repo may legitimately publish different apps from different
    workflows.
    """
    existing = _repo_publishers(session, owner, name, organisation_id)

    for publisher in existing:
        if _publisher_workflow(publisher) == workflow:
            return publisher["id"], "found"

    workflows_dir = root / ".github" / "workflows"
    orphaned = [
        publisher
        for publisher in existing
        if not (workflows_dir / _publisher_workflow(publisher)).exists()
    ]
    if len(orphaned) == 1:
        moved = _publisher_request(
            session,
            "PATCH",
            publisher_id=orphaned[0]["id"],
            body={"workflow": workflow},
            organisation_id=organisation_id,
        )
        return moved["id"], "renamed"

    created = _publisher_request(
        session,
        "POST",
        body={
            "provider": GITHUB_PROVIDER,
            "repository_owner": owner,
            "repository_name": name,
            "workflow": workflow,
        },
        organisation_id=organisation_id,
    )
    return created["id"], "created"


def _needs_registry_profile(entry: dict[str, Any]) -> bool:
    """Whether this app pulls from a container registry at all.

    A processor has no image, so no registry profile selects anything for it.
    """
    return bool(entry.get("image_name"))


def _patch_control_plane(
    entries: list[tuple[Path, dict[str, Any]]],
    *,
    root: Path,
    registry_profile: bool,
    trusted_publisher: bool,
    workflow: str,
) -> None:
    """The half of the migration that lives in the cloud, not the repo.

    Two things the file cannot say any more:

      * the container registry. Dropping `container_registry_profile_id` stops
        doover_config.json asserting a profile, but the app keeps whatever it was
        last told -- an external registry it can no longer pull from -- and
        publishing won't fix it, since the field is no longer in the payload.
      * the trusted publisher. CI authenticates by exchanging a GitHub OIDC token
        for one scoped to the publisher matching this repo and workflow, and an
        app is only releasable by the publisher it points at. Without this the
        first CI run fails at publish with nothing to mint against.

    Only ever touches the environment the CLI is pointed at, so migrating both
    means running this twice with `DOOVER_CONTROL_API_BASE_URL` set accordingly.
    Failures are reported, not raised: the repo-side migration is already on disk
    and is worth keeping.
    """
    # Imported here rather than at module scope: apps.py registers this command,
    # so importing it at the top would be circular.
    from .apps import _resolve_application_id, _resolve_staging, get_state

    try:
        client, _ = get_state()
    except Exception as exc:
        rich.print(
            f"[yellow]Not logged in ({exc}) -- skipped the control-plane half of "
            f"the migration. Log in and re-run to finish it.[/yellow]"
        )
        return

    staging = _resolve_staging(None)
    environment = "staging" if staging else "production"

    repository = _github_repository(root) if trusted_publisher else None
    if trusted_publisher and repository is None:
        rich.print(
            "[yellow]No GitHub remote here -- skipped the trusted publisher. "
            "CI publishes as the repository, so there is nothing to trust.[/yellow]"
        )

    # One publisher per (repository, workflow), shared by every app in the repo,
    # and created against the first app's organisation -- they publish from the
    # same workflow, so a second would be the same trust stated twice.
    publisher_id: Any = None

    for app_dir, entry in entries:
        name = entry["name"]
        try:
            app_config = LocalApplication.from_config(entry, app_dir)
            app_id = _resolve_application_id(client, app_config, staging=staging)
            if app_id is None:
                rich.print(
                    f"[yellow]'{name}' does not exist on {environment} yet -- "
                    f"publish it, then re-run to finish its cloud setup.[/yellow]"
                )
                continue

            body: dict[str, Any] = {}
            if registry_profile and _needs_registry_profile(entry):
                body["container_registry_profile_id"] = REGISTRY_PROFILE_IDS[staging]

            if repository is not None:
                if publisher_id is None:
                    publisher_id, action = _ensure_publisher(
                        state.session,
                        *repository,
                        workflow,
                        entry.get("organisation_id"),
                        root=root,
                    )
                    verb = {
                        "found": "Reused",
                        "renamed": "Moved",
                        "created": "Registered",
                    }[action]
                    rich.print(
                        f"[green]{verb} trusted publisher "
                        f"{repository[0]}/{repository[1]} ({workflow}) on "
                        f"{environment}.[/green]"
                    )
                body["publisher_id"] = str(publisher_id)

            if not body:
                continue

            client.applications.partial(str(app_id), body=body)
        except Exception as exc:
            rich.print(
                f"[red]Could not finish cloud setup for '{name}' on "
                f"{environment}: {exc}[/red]"
            )
        else:
            rich.print(f"[green]Updated '{name}' on {environment}.[/green]")


def migrate(
    app_fp: Annotated[
        Path,
        typer.Argument(help="Path to the repository to migrate."),
    ] = Path(),
    workflows: Annotated[
        bool,
        typer.Option(
            help="Replace the repo's CI workflows with the shared Doover one. "
            "Disable with --no-workflows to migrate doover_config.json only.",
        ),
    ] = True,
    workflow_ref: Annotated[
        str,
        typer.Option(help="Reusable workflow to call, as owner/repo/path@ref."),
    ] = DEFAULT_WORKFLOW_REF,
    widget_plugin: Annotated[
        bool,
        typer.Option(
            help="Update each widget's vendored ConcatenatePlugin.ts to the "
            "current one. Disable with --no-widget-plugin.",
        ),
    ] = True,
    registry_profile: Annotated[
        bool,
        typer.Option(
            help="Point each app at the Doover container registry on the control "
            "plane. Requires a login; disable with --no-registry-profile.",
        ),
    ] = True,
    trusted_publisher: Annotated[
        bool,
        typer.Option(
            help="Register this GitHub repository as the trusted publisher for "
            "each app, so CI can publish without a stored secret. Requires a "
            "login; disable with --no-trusted-publisher.",
        ),
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option(help="Show what would change without writing anything."),
    ] = False,
):
    """Migrate an app repository to the current config and CI format.

    Points images at the Doover container registry -- in doover_config.json and
    in the deployment/ compose files, which are what a device actually pulls --
    drops keys that no longer do anything, including the committed config/UI
    schemas that are generated from the app's source at publish time, and
    replaces the per-repo build, lint and test workflows with the shared
    reusable one. Widgets also get the current ConcatenatePlugin.ts, which each
    repo vendors a copy of, so a fix to it reaches the repo at all.

    Then does the half the repo cannot state for itself: points each app at the
    Doover-internal container registry, which the config file no longer names,
    and registers this GitHub repository as the app's trusted publisher so CI can
    release it with no stored secret. That half only touches the environment the
    CLI is pointed at, so run it once per environment.
    """
    root = app_fp.resolve()
    if not root.is_dir():
        rich.print(f"[red]{root} is not a directory.[/red]")
        raise typer.Exit(1)

    config_paths = _config_paths(root)
    if not config_paths:
        rich.print(f"[red]No doover_config.json found under {root}.[/red]")
        raise typer.Exit(1)

    changed = False
    # Every app in the repo, whichever config declared it. The control-plane pass
    # needs them all: the trusted publisher applies to each, the registry profile
    # only to the ones that pull an image.
    all_apps: list[tuple[Path, dict[str, Any]]] = []

    for config_path in config_paths:
        try:
            original = config_path.read_text()
            data = json.loads(original)
        except (OSError, ValueError) as exc:
            rich.print(f"[red]Could not read {config_path}: {exc}[/red]")
            raise typer.Exit(1)

        migrated_data = migrate_config(data)
        _apply_widget_install(migrated_data)
        all_apps.extend(
            (config_path.parent, entry)
            for entry in migrated_data.values()
            if isinstance(entry, dict) and "type" in entry
        )

        migrated = json.dumps(migrated_data, indent=4) + "\n"
        rel = config_path.relative_to(root)
        if migrated == original:
            rich.print(f"[dim]{rel} already up to date.[/dim]")
        else:
            changed = True
            if dry_run:
                rich.print(f"[yellow]Would rewrite {rel}[/yellow]")
            else:
                config_path.write_text(migrated)
                rich.print(f"[green]Rewrote {rel}[/green]")

        # The deployment folder ships its own copy of the image reference, and
        # that copy is the one a device pulls. Rewriting only the config leaves
        # the app registered against the new registry but still deploying the
        # old image.
        images = {
            image_key(entry["image_name"]): entry["image_name"]
            for entry in migrated_data.values()
            if isinstance(entry, dict) and entry.get("image_name")
        }
        # Deduped across entries: several apps routinely share one deployment
        # folder -- that is the case this whole pass exists for -- and visiting
        # the file once per app reported the same rewrite five times.
        compose_paths = sorted(
            {
                path
                for entry in migrated_data.values()
                if isinstance(entry, dict) and "type" in entry
                for path in _compose_paths(config_path.parent, entry)
            }
        )
        for compose_path in compose_paths:
            before = compose_path.read_text()
            after = migrate_compose(
                before, images, jinja=_is_jinja(compose_path, before)
            )
            if after != before:
                changed = True
                compose_rel = compose_path.relative_to(root)
                if dry_run:
                    rich.print(f"[yellow]Would rewrite {compose_rel}[/yellow]")
                else:
                    compose_path.write_text(after)
                    rich.print(f"[green]Rewrote {compose_rel}[/green]")

    if workflows:
        delete, write_path, content = _plan_workflows(root, workflow_ref)
        for path in delete:
            changed = True
            rel = path.relative_to(root)
            if dry_run:
                rich.print(f"[yellow]Would delete {rel}[/yellow]")
            else:
                path.unlink()
                rich.print(f"[green]Deleted {rel}[/green]")

        if write_path is not None:
            changed = True
            rel = write_path.relative_to(root)
            if dry_run:
                rich.print(f"[yellow]Would write {rel}[/yellow]")
            else:
                write_path.parent.mkdir(parents=True, exist_ok=True)
                write_path.write_text(content)
                rich.print(f"[green]Wrote {rel}[/green]")

    if widget_plugin:
        # Only files that are recognisably this plugin and not already current;
        # a repo's unrelated ConcatenatePlugin.ts keeps whatever it says.
        for path in plan_widget_plugins(root):
            changed = True
            rel = path.relative_to(root)
            if dry_run:
                rich.print(f"[yellow]Would update {rel}[/yellow]")
            else:
                path.write_text(PLUGIN_SOURCE)
                rich.print(f"[green]Updated {rel}[/green]")

    if (registry_profile or trusted_publisher) and all_apps:
        if dry_run:
            names = ", ".join(entry["name"] for _, entry in all_apps)
            rich.print(
                f"[yellow]Would update {names} on the control plane (registry "
                f"profile, trusted publisher).[/yellow]"
            )
        else:
            # Runs even when the files were already up to date: the control plane
            # is a separate half of the migration, and a repo can be migrated in
            # one environment and not the other.
            _patch_control_plane(
                all_apps,
                root=root,
                registry_profile=registry_profile,
                trusted_publisher=trusted_publisher,
                workflow=WORKFLOW_NAME,
            )

    if dry_run:
        rich.print("\n[dim]Dry run -- nothing was written.[/dim]")
        return

    if not changed:
        rich.print("[green]Repository already on the current format.[/green]")
        return

    rich.print(
        "\nMigrated. Review the diff, then republish the app:\n"
        "  [bold]doover app publish[/bold]"
    )
