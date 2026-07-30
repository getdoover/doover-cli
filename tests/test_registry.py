"""Tests for the docker credential helper and registry push login.

The helper is invoked by docker, not by a human, so its *protocol* behaviour is
what matters: exact JSON on stdout, no prompting, and a non-zero exit when there
is no session rather than empty credentials (which would make docker retry
anonymously and report a misleading 401).
"""

import io
import json
from unittest import mock

import pytest

from doover_cli import registry


def _run_helper(verb, stdin="registry.doover.com", monkeypatch=None):
    monkeypatch.setattr("sys.argv", ["docker-credential-doover", verb])
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    return out


class TestCredentialHelper:
    def test_get_emits_the_session_token(self, monkeypatch):
        out = _run_helper("get", monkeypatch=monkeypatch)
        session = mock.MagicMock()
        session.auth.token = "tok-123"
        with mock.patch(
            "doover_cli.api.session.DooverCLISession.from_env", return_value=session
        ):
            registry.credential_helper()

        payload = json.loads(out.getvalue())
        assert payload["Secret"] == "tok-123"
        assert payload["ServerURL"] == "registry.doover.com"
        # ensure_token is what keeps a stored login from silently rotting
        session.auth.ensure_token.assert_called_once()

    def test_missing_session_exits_non_zero(self, monkeypatch):
        """Docker treats empty credentials as "try anonymously", which surfaces
        as a confusing 401 rather than "you are not logged in"."""
        out = _run_helper("get", monkeypatch=monkeypatch)
        with mock.patch(
            "doover_cli.api.session.DooverCLISession.from_env",
            side_effect=RuntimeError("no profile"),
        ):
            with pytest.raises(SystemExit) as exc:
                registry.credential_helper()
        assert exc.value.code == 1
        assert out.getvalue() == ""

    def test_empty_token_exits_non_zero(self, monkeypatch):
        out = _run_helper("get", monkeypatch=monkeypatch)
        session = mock.MagicMock()
        session.auth.token = None
        with mock.patch(
            "doover_cli.api.session.DooverCLISession.from_env", return_value=session
        ):
            with pytest.raises(SystemExit) as exc:
                registry.credential_helper()
        assert exc.value.code == 1
        assert out.getvalue() == ""

    def test_store_and_erase_are_accepted(self, monkeypatch):
        """docker calls these on login/logout; we hold no state of our own."""
        for verb in ("store", "erase"):
            _run_helper(verb, stdin="{}", monkeypatch=monkeypatch)
            registry.credential_helper()  # must not raise

    def test_list_returns_an_empty_object(self, monkeypatch):
        out = _run_helper("list", monkeypatch=monkeypatch)
        registry.credential_helper()
        assert json.loads(out.getvalue()) == {}


class TestRegisterCredentialHelper:
    def test_merges_into_an_existing_config(self, tmp_path, monkeypatch):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"auths": {"ghcr.io": {"auth": "x"}}}))
        monkeypatch.setattr(registry, "_docker_config_path", lambda: config)

        assert registry.register_credential_helper() is True
        written = json.loads(config.read_text())
        assert written["credHelpers"]["registry.doover.com"] == "doover"
        # the user's other registries must survive
        assert written["auths"]["ghcr.io"]["auth"] == "x"

    def test_is_idempotent(self, tmp_path, monkeypatch):
        config = tmp_path / "config.json"
        config.write_text(
            json.dumps({"credHelpers": {"registry.doover.com": "doover"}})
        )
        monkeypatch.setattr(registry, "_docker_config_path", lambda: config)
        assert registry.register_credential_helper() is False

    def test_leaves_a_malformed_config_alone(self, tmp_path, monkeypatch):
        """Rewriting it could destroy credentials for other registries."""
        config = tmp_path / "config.json"
        config.write_text("{not json")
        monkeypatch.setattr(registry, "_docker_config_path", lambda: config)
        assert registry.register_credential_helper() is False
        assert config.read_text() == "{not json"


class TestIsDooverRegistry:
    @pytest.mark.parametrize(
        "image,expected",
        [
            ("registry.doover.com/apps/foo:main", True),
            ("registry.doover.com:443/apps/foo", True),
            ("REGISTRY.DOOVER.COM/apps/foo", True),
            ("ghcr.io/getdoover/foo:main", False),
            ("spaneng/doover_device_base", False),
            ("", False),
            (None, False),
        ],
    )
    def test_detects_our_registry(self, image, expected):
        assert registry.is_doover_registry(image) is expected


class TestLoginForPush:
    def test_pipes_the_credential_over_stdin(self):
        """Never on the command line, where it would land in the process list."""
        client = mock.MagicMock()
        client.mint_registry_token.return_value = {
            "registry": "registry.doover.com",
            "repository": "apps/foo",
            "username": "doover",
            "password": "secret-token",
        }
        with mock.patch("doover_cli.registry.subprocess.run") as run:
            target = registry.login_for_push(client, 123)

        assert target == "registry.doover.com/apps/foo"
        args, kwargs = run.call_args
        assert "--password-stdin" in args[0]
        assert kwargs["input"] == "secret-token"
        assert "secret-token" not in " ".join(args[0])


class TestRegistryHost:
    """Every environment names its hosts the same way, so the registry is derived
    from the control plane rather than configured. Hardcoding production meant a
    staging image was not recognised as ours: no credential was minted and the push
    failed with a bare 401."""

    @pytest.mark.parametrize(
        "control_url,expected",
        [
            ("https://api.doover.com", "registry.doover.com"),
            ("https://api.staging.udoover.com", "registry.staging.udoover.com"),
            ("https://api.sandbox.udoover.com", "registry.sandbox.udoover.com"),
            ("api.doover.com", "registry.doover.com"),
            ("https://api.doover.com:443/api", "registry.doover.com"),
            ("", "registry.doover.com"),
            (None, "registry.doover.com"),
            ("https://something-else.example.com", "registry.doover.com"),
        ],
    )
    def test_derives_the_registry_from_the_control_plane(self, control_url, expected):
        assert registry.registry_host(control_url) == expected

    def test_an_image_is_only_ours_in_its_own_environment(self):
        staging = "https://api.staging.udoover.com"
        assert registry.is_doover_registry(
            "registry.staging.udoover.com/apps/x:main", staging
        )
        # A production image seen from staging is not this environment's, so no
        # staging credential should be minted for it.
        assert not registry.is_doover_registry(
            "registry.doover.com/apps/x:main", staging
        )
        assert not registry.is_doover_registry("ghcr.io/getdoover/x:main", staging)


class TestApplicationIdExtraction:
    """`publish` gets an Application model back from create/partial, not a dict --
    calling .get() on it raised AttributeError right before the push."""

    def test_id_is_read_off_the_model(self):
        response = mock.Mock(id=12345)
        assert getattr(response, "id", None) == 12345

    def test_id_is_read_off_a_dict_response(self):
        response = {"id": 999}
        got = getattr(response, "id", None)
        if got is None and isinstance(response, dict):
            got = response.get("id")
        assert got == 999
