import os
from importlib import metadata

import click
import sentry_sdk

from .state import state

DEFAULT_DSN = (
    "https://ad30b28431235ad979a0857edfba6618@"
    "o4507800638783488.ingest.us.sentry.io/4511029472067584"
)

_initialized = False


def is_enabled() -> bool:
    value = os.environ.get("DOOVER_SENTRY_ENABLED")
    if value is None:
        return True

    return value.strip().lower() not in {"0", "false", "no", "off"}


def current_command_path() -> str | None:
    ctx = click.get_current_context(silent=True)
    if ctx is None or not ctx.command_path:
        return None

    parts = ctx.command_path.split()
    if len(parts) <= 1:
        return parts[0] if parts else None

    return " ".join(parts[1:])


def _before_send(event, hint):
    exc_info = hint.get("exc_info") if hint else None
    if exc_info:
        _, exc, _ = exc_info
        if isinstance(exc, (click.exceptions.Exit, click.Abort)):
            return None

    return event


def init_sentry() -> None:
    global _initialized

    if _initialized or not is_enabled():
        return

    try:
        version = metadata.version("doover-cli")
    except metadata.PackageNotFoundError:
        version = "unknown"

    sentry_sdk.init(
        dsn=os.environ.get("DOOVER_SENTRY_DSN", DEFAULT_DSN),
        release=f"doover-cli@{version}",
        environment=os.environ.get("DOOVER_SENTRY_ENVIRONMENT", "production"),
        send_default_pii=False,
        include_local_variables=False,
        sample_rate=1.0,
        before_send=_before_send,
    )
    _initialized = True


def _capture_exception(
    exc: BaseException,
    *,
    handled: bool,
    command: str | None,
    message: str | None = None,
) -> None:
    if not _initialized or not is_enabled():
        return

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("handled", str(handled).lower())
        if command:
            scope.set_tag("command", command)
        scope.set_tag("debug", str(state.debug).lower())
        scope.set_tag("renderer", str(state.renderer_name).lower())

        config_manager = state.config_manager
        if config_manager is not None and config_manager.current_profile:
            scope.set_tag("profile", config_manager.current_profile)

        if message:
            scope.set_extra("message", message)

        sentry_sdk.capture_exception(exc)


def capture_handled_exception(
    exc: BaseException, *, command: str, message: str | None = None
) -> None:
    _capture_exception(exc, handled=True, command=command, message=message)


def flush_sentry(timeout: float = 2.0) -> None:
    if not _initialized:
        return

    sentry_sdk.flush(timeout=timeout)
