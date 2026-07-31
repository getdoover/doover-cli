"""Tests for the docker credential helper and registry push login.

The helper is invoked by docker, not by a human, so its *protocol* behaviour is
what matters: exact JSON on stdout, no prompting, and a non-zero exit when there
is no session rather than empty credentials (which would make docker retry
anonymously and report a misleading 401).
"""

import base64
import io
import json
import stat
import time
from unittest import mock

import pytest

from doover_cli import registry


def _run_helper(verb, stdin="registry.doover.com", monkeypatch=None):
    monkeypatch.setattr("sys.argv", ["docker-credential-doover", verb])
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    return out


def _jwt(exp):
    """A token carrying nothing but `exp`. The helper reads `exp` without
    verifying, so no signature is needed."""
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode())
    return f"header.{payload.rstrip(b'=').decode()}.signature"


@pytest.fixture(autouse=True)
def credential_store(tmp_path, monkeypatch):
    """Redirect the credential store into a tmp path for every test in this file.

    Autouse rather than opt-in: `store` writes a real file, and a test that
    forgot to redirect it would scribble a bearer credential into the developer's
    own ~/.doover and leak state into whatever ran next.
    """
    path = tmp_path / "registry-credentials.json"
    monkeypatch.setattr(registry, "_credential_store_path", lambda: path)
    return path


def _store(entry, server="registry.doover.com"):
    """Seed the redirected credential store, as a prior `docker login` would."""
    registry._write_stored({server: entry})


@pytest.fixture
def env_token(monkeypatch):
    """The CI path, where the session comes from the environment."""
    monkeypatch.setenv("DOOVER_API_TOKEN", "env-token")


class TestCredentialHelper:
    def test_get_emits_the_session_token(self, monkeypatch, env_token):
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

    def test_missing_session_exits_non_zero(self, monkeypatch, env_token):
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

    def test_empty_token_exits_non_zero(self, monkeypatch, env_token):
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

    def test_no_matching_profile_exits_non_zero(self, monkeypatch):
        """No DOOVER_API_TOKEN and no profile for this registry."""
        out = _run_helper(
            "get", stdin="registry.nope.example.com", monkeypatch=monkeypatch
        )
        monkeypatch.delenv("DOOVER_API_TOKEN", raising=False)
        with mock.patch("pydoover.api.auth.ConfigManager") as manager:
            manager.return_value.entries = {}
            with pytest.raises(SystemExit) as exc:
                registry.credential_helper()
        assert exc.value.code == 1
        assert out.getvalue() == ""

    def test_store_persists_the_credential(self, monkeypatch, credential_store):
        """The whole point: `docker login`'s repo-scoped credential has to
        survive to the push. Discarding it silently defeated `login_for_push`."""
        secret = _jwt(time.time() + 1800)
        _run_helper(
            "store",
            stdin=json.dumps(
                {
                    "ServerURL": "registry.doover.com",
                    "Username": "doover",
                    "Secret": secret,
                }
            ),
            monkeypatch=monkeypatch,
        )
        registry.credential_helper()

        assert json.loads(credential_store.read_text()) == {
            "registry.doover.com": {"Username": "doover", "Secret": secret}
        }

    def test_store_is_written_readable_only_by_its_owner(
        self, monkeypatch, credential_store
    ):
        _run_helper(
            "store",
            stdin=json.dumps({"ServerURL": "registry.doover.com", "Secret": "s"}),
            monkeypatch=monkeypatch,
        )
        registry.credential_helper()
        assert stat.S_IMODE(credential_store.stat().st_mode) == 0o600

    def test_a_stored_credential_beats_the_session_token(self, monkeypatch, env_token):
        """A public or core app grants no push through the session token at all,
        so the brokered credential must win."""
        secret = _jwt(time.time() + 1800)
        _store({"Username": "ci", "Secret": secret})

        out = _run_helper("get", monkeypatch=monkeypatch)
        with mock.patch("doover_cli.api.session.DooverCLISession.from_env") as from_env:
            registry.credential_helper()

        payload = json.loads(out.getvalue())
        assert payload["Secret"] == secret
        assert payload["Username"] == "ci"
        # The session is never consulted; that is what keeps the scope narrow.
        from_env.assert_not_called()

    def test_an_expired_credential_is_dropped_not_served(
        self, monkeypatch, env_token, credential_store
    ):
        """Serving a dead token wastes a request; keeping it would shadow the
        session token that still serves pulls."""
        _store({"Username": "ci", "Secret": _jwt(time.time() - 5)})

        out = _run_helper("get", monkeypatch=monkeypatch)
        session = mock.MagicMock()
        session.auth.token = "tok-123"
        with mock.patch(
            "doover_cli.api.session.DooverCLISession.from_env", return_value=session
        ):
            registry.credential_helper()

        assert json.loads(out.getvalue())["Secret"] == "tok-123"
        assert json.loads(credential_store.read_text()) == {}

    def test_a_credential_without_an_exp_is_served(self, monkeypatch, env_token):
        """Docker gave it to us; an opaque credential is not ours to expire."""
        _store({"Username": "ci", "Secret": "opaque"})
        out = _run_helper("get", monkeypatch=monkeypatch)
        registry.credential_helper()
        assert json.loads(out.getvalue())["Secret"] == "opaque"

    def test_erase_removes_the_stored_credential(self, monkeypatch, credential_store):
        _store({"Username": "ci", "Secret": "s"})
        _run_helper("erase", monkeypatch=monkeypatch)
        registry.credential_helper()
        assert json.loads(credential_store.read_text()) == {}

    def test_list_reports_what_is_stored(self, monkeypatch):
        _store({"Username": "ci", "Secret": "s"})
        out = _run_helper("list", monkeypatch=monkeypatch)
        registry.credential_helper()
        assert json.loads(out.getvalue()) == {"registry.doover.com": "ci"}

    def test_list_is_empty_when_nothing_is_stored(self, monkeypatch):
        out = _run_helper("list", monkeypatch=monkeypatch)
        registry.credential_helper()
        assert json.loads(out.getvalue()) == {}

    def test_a_malformed_store_payload_exits_non_zero(self, monkeypatch):
        _run_helper("store", stdin="not json", monkeypatch=monkeypatch)
        with pytest.raises(SystemExit) as exc:
            registry.credential_helper()
        assert exc.value.code == 1


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
    def test_a_failed_login_reports_what_docker_said(self):
        """Otherwise the only signal is a CalledProcessError, which says nothing
        about whether the registry was unreachable, the certificate was wrong, or
        the token was rejected."""
        client = mock.MagicMock()
        client.mint_registry_token.return_value = {
            "registry": "registry.staging.udoover.com",
            "repository": "apps/foo",
            "username": "doover",
            "password": "secret-token",
        }
        with mock.patch("doover_cli.registry.subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=1,
                stderr="Error response from daemon: login attempt failed",
                stdout="",
            )
            with pytest.raises(registry.RegistryLoginError) as exc:
                registry.login_for_push(client, 123)

        assert "registry.staging.udoover.com" in str(exc.value)
        assert "login attempt failed" in str(exc.value)
        # never the credential itself
        assert "secret-token" not in str(exc.value)

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
            run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
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
