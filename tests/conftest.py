from pathlib import Path

import pytest

from pydoover.api.auth import ConfigManager

from doover_cli.utils.state import state


@pytest.fixture(autouse=True)
def isolate_doover_config(monkeypatch, tmp_path):
    config_dir = tmp_path / ".doover"
    config_file = config_dir / "config"
    monkeypatch.setattr(ConfigManager, "directory", str(config_dir))
    monkeypatch.setattr(ConfigManager, "filepath", str(config_file))
    yield Path(config_file)


@pytest.fixture(autouse=True)
def stub_registry_manifest_reads(monkeypatch):
    """Keep `app publish` tests off docker and the network.

    Publishing reads the pushed image back from the registry to catch a push that
    landed an index without the manifests it references. The push itself is faked
    in these tests, so there is nothing to read back: answer every lookup as a
    complete single-platform image. Tests of the verification override this.
    """
    monkeypatch.setattr(
        "doover_cli.apps.apps._read_manifest",
        lambda ref: (
            "present",
            {"mediaType": "application/vnd.oci.image.manifest.v1+json"},
        ),
    )


@pytest.fixture(autouse=True)
def reset_cli_state(monkeypatch):
    monkeypatch.delenv("DOOVER_API_TOKEN", raising=False)
    monkeypatch.delenv("DOOVER_DATA_API_BASE_URL", raising=False)

    state.agent_id = None
    state.profile_name = "default"
    state.debug = False
    state.json = False
    state.config_manager = None
    state._renderer = None
    state._session = None
