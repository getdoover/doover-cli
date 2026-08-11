from pathlib import Path

from doover_cli.apps.widget_plugin import (
    PLUGIN_FILENAME,
    PLUGIN_SOURCE,
    find_widget_plugins,
    is_widget_plugin,
    plan_widget_plugins,
)

# An older vendored copy: same class, same hook, none of the build identity.
LEGACY_PLUGIN = """\
import * as fs from 'fs';
import * as path from 'path';
import {Compiler, Compilation} from 'webpack';

class ConcatenatePlugin {
    apply(compiler: Compiler): void {
        compiler.hooks.afterEmit.tapAsync('ConcatenatePlugin', () => {});
    }
}

export default ConcatenatePlugin;
"""


def _widget(root: Path, directory: str, content: str) -> Path:
    path = root / directory / PLUGIN_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_current_plugin_carries_the_build_identity():
    # The whole point of the migration: without these the widget shares its
    # globals with every other build of itself in the page.
    assert "uniqueName" in PLUGIN_SOURCE
    assert "chunkLoadingGlobal" in PLUGIN_SOURCE
    assert "MF_BUILD_VERSION" in PLUGIN_SOURCE


def test_legacy_copy_is_recognised_as_ours(tmp_path):
    assert is_widget_plugin(_widget(tmp_path, "dashboard-widget", LEGACY_PLUGIN))


def test_unrelated_file_of_the_same_name_is_left_alone(tmp_path):
    path = _widget(tmp_path, "src", "export default class ConcatenatePlugin {}\n")
    assert not is_widget_plugin(path)
    assert find_widget_plugins(tmp_path) == []


def test_node_modules_is_not_walked(tmp_path):
    _widget(tmp_path, "node_modules/some-pkg", LEGACY_PLUGIN)
    assert find_widget_plugins(tmp_path) == []


def test_every_widget_in_a_multi_widget_repo_is_found(tmp_path):
    first = _widget(tmp_path, "widget-a", LEGACY_PLUGIN)
    second = _widget(tmp_path, "nested/widget-b", LEGACY_PLUGIN)
    assert find_widget_plugins(tmp_path) == sorted([first, second])


def test_a_current_copy_is_not_replanned(tmp_path):
    _widget(tmp_path, "dashboard-widget", PLUGIN_SOURCE)
    assert plan_widget_plugins(tmp_path) == []


def test_a_stale_copy_is_planned(tmp_path):
    path = _widget(tmp_path, "dashboard-widget", LEGACY_PLUGIN)
    assert plan_widget_plugins(tmp_path) == [path]
