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
def reset_cli_state(monkeypatch):
    monkeypatch.delenv("DOOVER_API_TOKEN", raising=False)
    monkeypatch.delenv("DOOVER_DATA_API_BASE_URL", raising=False)

    state.agent_id = None
    state.profile_name = "default"
    state.debug = False
    state.json = False
    state.config_manager = None
    state._session = None
