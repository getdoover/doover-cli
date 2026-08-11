from pathlib import Path

from doover_cli.apps.migrate import (
    IMAGE_PLACEHOLDER,
    _compose_paths,
    _is_jinja,
    image_key,
    migrate_compose,
)

# The shape that broke: two apps, one compose file, one `image:` line. The
# literal can only ever name one of them, so the rendered placeholder is the
# only reference that is right for both.
SHARED_TEMPLATE = """\
services:
  leachate_telemetry:
    image: spaneng/leachate-telemetry:doover-2
    entrypoint: ["{{ 'doover-app-run-doovit-airwell' if APPLICATION_NAME == 'leachate_telemetry' else 'doover-app-run-doovit-tags' }}"]
"""

IMAGES = {
    "leachate_telemetry": "registry.doover.com/apps/leachate_telemetry:doover-2",
    "leachate_doovit_scadapack": (
        "registry.doover.com/apps/leachate_doovit_scadapack:doover-2"
    ),
}


def _deployment(root: Path, filename: str, content: str) -> Path:
    path = root / "deployment" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_rendered_deployment_files_are_found(tmp_path):
    # The original bug: `.template` is the final suffix, so matching on
    # `path.suffix` skipped the file entirely and the repo migrated with a stale
    # image still pinned in the deployment it actually ships.
    template = _deployment(tmp_path, "docker-compose.yml.template", SHARED_TEMPLATE)
    assert _compose_paths(tmp_path, {}) == [template]


def test_plain_and_jinja_deployment_files_are_both_found(tmp_path):
    plain = _deployment(tmp_path, "docker-compose.yml", "services: {}\n")
    j2 = _deployment(tmp_path, "docker-compose.yaml.j2", "services: {}\n")
    assert _compose_paths(tmp_path, {}) == sorted([plain, j2])


def test_unrelated_files_are_left_out(tmp_path):
    _deployment(tmp_path, "README.md", "notes\n")
    _deployment(tmp_path, "values.ymlish", "not yaml\n")
    assert _compose_paths(tmp_path, {}) == []


def test_custom_deployment_folder_is_honoured(tmp_path):
    path = tmp_path / "custom" / "docker-compose.yml.template"
    path.parent.mkdir(parents=True)
    path.write_text(SHARED_TEMPLATE)
    assert _compose_paths(tmp_path, {"deployment_folder": "custom"}) == [path]


def test_jinja_detected_from_suffix_and_from_body():
    assert _is_jinja(Path("docker-compose.yml.template"), "services: {}\n")
    assert _is_jinja(Path("docker-compose.yaml.j2"), "services: {}\n")
    assert _is_jinja(Path("docker-compose.yml"), "image: {{ IMAGE_NAME }}\n")
    assert not _is_jinja(Path("docker-compose.yml"), "image: nginx:latest\n")


def test_rendered_file_gets_the_placeholder():
    after = migrate_compose(SHARED_TEMPLATE, IMAGES, jinja=True)
    assert f"image: {IMAGE_PLACEHOLDER}" in after
    assert "spaneng/leachate-telemetry" not in after
    # Only the image line moves; the entrypoint conditional is how one image
    # serves two apps and must survive untouched.
    assert "doover-app-run-doovit-airwell" in after
    assert "doover-app-run-doovit-tags" in after


def test_plain_file_gets_the_literal_reference():
    before = "services:\n  app:\n    image: spaneng/leachate-telemetry:doover-2\n"
    after = migrate_compose(before, IMAGES, jinja=False)
    assert IMAGES["leachate_telemetry"] in after
    assert IMAGE_PLACEHOLDER not in after


def test_sidecar_tag_survives_the_registry_move():
    # device-compliance runs a dnsmasq sidecar built from its own repository
    # under a different tag. Both references reduce to the same app, so taking
    # the registered reference wholesale silently replaced the sidecar with a
    # second copy of the app.
    before = (
        "services:\n"
        "  dnsmasq:\n"
        "    image: spaneng/device-compliance:dnsmasq\n"
        "  device_compliance:\n"
        "    image: spaneng/device-compliance:main\n"
    )
    images = {"device_compliance": "registry.doover.com/apps/device_compliance:main"}
    after = migrate_compose(before, images, jinja=False)
    assert "registry.doover.com/apps/device_compliance:dnsmasq" in after
    assert "registry.doover.com/apps/device_compliance:main" in after


def test_untagged_reference_takes_the_registered_tag():
    # Nothing was spelled out, so the config is the only opinion on the wire.
    before = "    image: spaneng/leachate-telemetry\n"
    after = migrate_compose(before, IMAGES, jinja=False)
    assert after.strip() == f"image: {IMAGES['leachate_telemetry']}"


def test_rewrite_is_idempotent():
    once = migrate_compose(SHARED_TEMPLATE, IMAGES, jinja=True)
    assert migrate_compose(once, IMAGES, jinja=True) == once


def test_third_party_images_are_untouched():
    # A sidecar belongs to nobody in this repo; rewriting it would point the
    # device at an app image that does not do the sidecar's job.
    before = (
        "services:\n  gateway:\n    image: rakwireless/udp-packet-forwarder:latest\n"
    )
    assert migrate_compose(before, IMAGES, jinja=True) == before


def test_quoting_and_trailing_comments_survive():
    before = '    image: "spaneng/leachate-telemetry:doover-2"  # pinned\n'
    after = migrate_compose(before, IMAGES, jinja=True)
    assert after == f'    image: "{IMAGE_PLACEHOLDER}"  # pinned\n'


def test_image_key_folds_registry_namespace_and_separator():
    assert image_key("spaneng/leachate-telemetry:doover-2") == "leachate_telemetry"
    assert (
        image_key("registry.doover.com/apps/leachate_telemetry:doover-2")
        == "leachate_telemetry"
    )
