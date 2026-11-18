import json
from pathlib import Path

import pytest

from doover_cli.utils.apps import app_files_body, parse_app_files


def test_files_parse_and_upload_each_file_once(tmp_path: Path):
    entries = parse_app_files(
        [
            {"channel": "{app_key}_widget", "fp": ["dist/widget.js"]},
            {
                "channel": "dv-script-config",
                "fp": ["build/gate.dvs"],
                "content_type": "application/x-dvs",
            },
        ],
        tmp_path,
    )
    body = app_files_body(entries)
    assert json.loads(body["manifest"]) == [
        {"channel": "{app_key}_widget", "files": ["widget.js"]},
        {
            "channel": "dv-script-config",
            "files": ["gate.dvs"],
            "content_type": "application/x-dvs",
        },
    ]
    assert body["file"] == [tmp_path / "dist/widget.js", tmp_path / "build/gate.dvs"]
    assert parse_app_files(None, tmp_path) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"channel": "a", "fp": ["x"]},  # not a list
        [{"fp": ["x"]}],  # no channel
        [{"channel": "a", "fp": ["x"]}, {"channel": "a", "fp": ["y"]}],  # twice
        [{"channel": "a", "fp": "x"}],  # fp not a list
        [{"channel": "a", "fp": ["x/f.bin"]}, {"channel": "b", "fp": ["y/f.bin"]}],
    ],
)
def test_files_refuse_what_the_control_plane_would(raw, tmp_path: Path):
    with pytest.raises(ValueError):
        parse_app_files(raw, tmp_path)
