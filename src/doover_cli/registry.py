"""Docker integration for the doover container registry.

Two things live here:

* ``credential_helper`` -- the ``docker-credential-doover`` entry point. Docker
  finds credential helpers by name on PATH, so installing the CLI is what makes
  ``docker pull registry.doover.com/...`` work; there is nothing else to install
  and no ``docker login`` to run. It hands docker the current session token, and
  the registry's token realm reads the caller's permissions from their own
  ``dv-registry`` channel -- so a user reaches exactly the apps they can reach in
  the UI, resolved live.

* ``login_for_push`` -- a ``docker login`` with a credential scoped to one
  repository, for pushing a build. Push needs the narrow credential rather than
  the session, because it is minted by the control plane against the app's
  publish permission.

The helper protocol is deliberately minimal: docker writes a registry host on
stdin and expects ``{"ServerURL","Username","Secret"}`` on stdout for ``get``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

DEFAULT_REGISTRY = "registry.doover.com"


def registry_host(control_base_url: str | None = None) -> str:
    """The registry that belongs to a given control plane.

    Derived rather than configured: every environment names its hosts the same
    way, so api.doover.com pairs with registry.doover.com and
    api.staging.udoover.com with registry.staging.udoover.com. Hardcoding the
    production host meant a staging image was not recognised as ours, so no
    credential was minted and the push failed with a bare 401.
    """
    if not control_base_url:
        return DEFAULT_REGISTRY
    host = control_base_url.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    if host.startswith("api."):
        return "registry." + host[len("api.") :]
    return DEFAULT_REGISTRY


def _docker_config_path():
    from pathlib import Path

    return Path.home() / ".docker" / "config.json"


def register_credential_helper(registry: str = DEFAULT_REGISTRY) -> bool:
    """Point docker at our helper for `registry`, leaving the rest of the file
    alone. Returns True if the config was changed.

    Merged rather than rewritten: this file is the user's, and usually holds
    credentials for other registries.
    """
    path = _docker_config_path()
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        # A malformed or unreadable config is the user's to fix; silently
        # replacing it could lose their other registry credentials.
        return False

    helpers = config.setdefault("credHelpers", {})
    if helpers.get(registry) == "doover":
        return False

    helpers[registry] = "doover"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return True


def credential_helper() -> None:
    """`docker-credential-doover` entry point.

    Never prompts. Docker captures stdin and stdout, so an interactive login
    would hang the pull; and returning empty credentials would make docker retry
    anonymously and report a misleading 401. So a missing session exits non-zero
    with an explanation on stderr instead.
    """
    verb = sys.argv[1] if len(sys.argv) > 1 else ""

    # store/erase exist because docker calls them on `docker login`/`logout`. We
    # hold no state of our own, so they succeed and do nothing.
    if verb in ("store", "erase"):
        sys.stdin.read()
        return
    if verb == "list":
        print(json.dumps({}))
        return
    if verb != "get":
        print(f"unknown verb: {verb!r}", file=sys.stderr)
        raise SystemExit(2)

    server_url = sys.stdin.read().strip() or DEFAULT_REGISTRY

    # Imported here, not at module scope: docker invokes this on every registry
    # operation, and the CLI's import graph is far too heavy to pay for that.
    from .api.session import DooverCLISession

    try:
        session = DooverCLISession.from_env()
        auth = session.auth
        auth.ensure_token()
        token = auth.token
    except Exception as e:  # noqa: BLE001 - any failure means "not logged in"
        print(
            f"doover: no usable session for {server_url} ({e}).\n"
            f"Run `doover login` and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    if not token:
        print(
            "doover: not logged in. Run `doover login` and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # The username is a label only -- the realm resolves the agent from the
    # token's claims and ignores it.
    print(json.dumps({"ServerURL": server_url, "Username": "doover", "Secret": token}))


def is_doover_registry(
    image_name: str | None, control_base_url: str | None = None
) -> bool:
    """Whether an image lives on this environment's doover registry, and so needs
    a credential minted by the control plane rather than the user's own docker
    login."""
    if not image_name:
        return False
    host = image_name.split("/", 1)[0].split(":")[0].lower()
    return host == registry_host(control_base_url)


def publish_github_output(image: str) -> None:
    """Expose the image reference to later workflow steps.

    Lets a workflow stay identical across app repos: the reference comes from the
    app's own doover_config.json rather than being spelled out in the yaml, which
    also removes the chance of it drifting from the registered image name.
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    try:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"image={image}\n")
    except OSError as e:
        print(f"could not write GITHUB_OUTPUT: {e}", file=sys.stderr)


def login_for_push(control_client, application_id: int | str) -> str:
    """`docker login` with a credential scoped to one application's repository.

    Returns the repository path to push to. Raises if the app does not publish to
    the doover registry, which is what stops a stale config pushing into a
    repository nothing will pull.
    """
    result = control_client.mint_registry_token(application_id)
    registry = result["registry"]
    subprocess.run(
        ["docker", "login", registry, "-u", result["username"], "--password-stdin"],
        input=result["password"],
        text=True,
        check=True,
        capture_output=True,
    )
    return f"{registry}/{result['repository']}"
