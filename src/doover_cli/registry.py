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

Registering the helper for a host means docker routes *every* credential
operation for it here, ``store`` included -- so the helper has to persist what
``docker login`` gives it. It used to discard it, which silently defeated
``login_for_push``: the scoped credential went nowhere and the subsequent push
fell back to the session token. For a PUBLIC or CORE app that token carries no
push scope at all (doover-control's ``entitlements_for_user`` excludes those
apps), so the brokered credential is not an optimisation, it is the only thing
that can push.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time


class RegistryLoginError(RuntimeError):
    """`docker login` to the registry failed, carrying what docker reported."""


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


def _credential_store_path():
    from pathlib import Path

    return Path.home() / ".doover" / "registry-credentials.json"


def _read_stored() -> dict:
    try:
        entries = json.loads(_credential_store_path().read_text())
    except (OSError, ValueError):
        # Nothing stored, or a file we did not write. Falling back to the session
        # token is always safe; the worst case is a clear entitlement error.
        return {}
    return entries if isinstance(entries, dict) else {}


def _write_stored(entries: dict) -> None:
    path = _credential_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from the moment it exists: these are bearer credentials for pushing
    # images, so the mode cannot be applied as an afterthought.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(entries, fh)


def _seconds_until_expiry(secret: str) -> float | None:
    """Seconds left on `secret`, or None if it carries no readable `exp`.

    Decoded without verifying the signature: the realm is the only thing that
    needs to trust this token, and all the helper needs to know is whether
    handing it to docker is pointless. A credential that is not a JWT is treated
    as non-expiring -- docker gave it to us, so it is not ours to second-guess.
    """
    try:
        payload = secret.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return float(exp) - time.time()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


# A push credential lives 30 minutes. Handing docker one with only seconds left
# buys a failed request rather than a completed upload.
EXPIRY_MARGIN_SECONDS = 30


def _token_for_registry(server_url: str) -> str:
    """A session token valid for `server_url`'s environment.

    Docker hands the helper a registry host and nothing else -- no `--profile`,
    no environment -- so the profile has to be recovered from that host.
    Whichever profile's control plane pairs with this registry is the one holding
    the right token, which is the same pairing `registry_host` applies going the
    other way.

    Matched on the derived host rather than the profile *name*: several profiles
    routinely point at the same environment under different names, and a staging
    push must not be signed with a production token. For the same reason every
    match is tried rather than just the first -- a long-lived config accumulates
    profiles whose refresh token has since been invalidated, and one of those
    sitting earlier in the file must not mask the one that still works.
    """
    # Imported here, not at module scope: docker invokes this on every registry
    # operation, and the CLI's import graph is far too heavy to pay for that.
    from .api.session import DooverCLISession

    # Set in CI, where there is no profile config to read.
    if os.environ.get("DOOVER_API_TOKEN"):
        session = DooverCLISession.from_env()
        session.auth.ensure_token()
        if not session.auth.token:
            # Returning an empty secret would make docker retry anonymously and
            # report a 401 that looks like a permissions problem.
            raise RuntimeError("session produced no token")
        return session.auth.token

    from pydoover.api.auth import ConfigManager

    manager = ConfigManager()
    candidates = []
    for name, profile in manager.entries.items():
        control_url = profile.control_base_url
        if not profile.token or not control_url:
            continue
        host = control_url.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
        # `registry_host` falls back to production for anything that isn't an
        # `api.` host, so a local profile would otherwise answer for
        # registry.doover.com.
        if host.startswith("api.") and registry_host(control_url) == server_url:
            candidates.append(name)

    if not candidates:
        raise RuntimeError(f"no logged-in profile has a control plane for {server_url}")

    failures = []
    for name in candidates:
        try:
            session = DooverCLISession.from_profile(name, config_manager=manager)
            session.auth.ensure_token()
        except Exception as e:  # noqa: BLE001 - try the next profile
            failures.append(f"{name}: {e}")
            continue
        if session.auth.token:
            return session.auth.token
        failures.append(f"{name}: no token after refresh")

    raise RuntimeError("; ".join(failures))


def credential_helper() -> None:
    """`docker-credential-doover` entry point.

    Never prompts. Docker captures stdin and stdout, so an interactive login
    would hang the pull; and returning empty credentials would make docker retry
    anonymously and report a misleading 401. So a missing session exits non-zero
    with an explanation on stderr instead.
    """
    verb = sys.argv[1] if len(sys.argv) > 1 else ""

    # `docker login` sends the credential here as JSON. Keeping it is what makes
    # a repo-scoped push credential survive to the push.
    if verb == "store":
        try:
            entry = json.loads(sys.stdin.read())
        except ValueError as e:
            print(f"doover: malformed credential on stdin ({e})", file=sys.stderr)
            raise SystemExit(1) from e
        entries = _read_stored()
        entries[entry.get("ServerURL") or DEFAULT_REGISTRY] = {
            "Username": entry.get("Username") or "doover",
            "Secret": entry.get("Secret") or "",
        }
        _write_stored(entries)
        return

    # `docker logout` sends the bare host.
    if verb == "erase":
        entries = _read_stored()
        if entries.pop(sys.stdin.read().strip(), None) is not None:
            _write_stored(entries)
        return

    if verb == "list":
        print(
            json.dumps(
                {
                    server: entry.get("Username", "doover")
                    for server, entry in _read_stored().items()
                }
            )
        )
        return
    if verb != "get":
        print(f"unknown verb: {verb!r}", file=sys.stderr)
        raise SystemExit(2)

    server_url = sys.stdin.read().strip() or DEFAULT_REGISTRY

    # A stored credential wins over the session token: it is the narrow one the
    # control plane brokered for a specific repository, and for a public or core
    # app it is the only one that carries push at all.
    stored = _read_stored().get(server_url)
    if stored:
        remaining = _seconds_until_expiry(stored.get("Secret", ""))
        if remaining is None or remaining > EXPIRY_MARGIN_SECONDS:
            print(
                json.dumps(
                    {
                        "ServerURL": server_url,
                        "Username": stored.get("Username", "doover"),
                        "Secret": stored.get("Secret", ""),
                    }
                )
            )
            return
        # Dropped rather than kept and skipped, so a dead push credential cannot
        # keep shadowing the session token that would still serve pulls.
        entries = _read_stored()
        entries.pop(server_url, None)
        _write_stored(entries)

    try:
        token = _token_for_registry(server_url)
    except Exception as e:  # noqa: BLE001 - any failure means "not logged in"
        print(
            f"doover: no usable session for {server_url} ({e}).\n"
            f"Run `doover login` and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

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
    completed = subprocess.run(
        ["docker", "login", registry, "-u", result["username"], "--password-stdin"],
        input=result["password"],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        # Surface what docker said. Swallowing it leaves only a
        # CalledProcessError, which says nothing about whether the registry was
        # unreachable, the certificate was wrong, or the token was rejected.
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RegistryLoginError(
            f"docker login to {registry} failed: {detail or 'no output from docker'}"
        )
    return f"{registry}/{result['repository']}"
