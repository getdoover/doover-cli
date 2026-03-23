from types import SimpleNamespace

import click
import pytest
from pydoover.models.control import DeviceType

from doover_cli.api import ControlClientUnavailableError
from doover_cli.utils.crud.lookup import (
    LookupChoice,
    load_control_model_choices,
    resolve_control_model_class,
    resolve_resource_lookup,
    resource_autocomplete,
)


def _resource_methods(**kwargs):
    return SimpleNamespace(**kwargs)


class FakeLookupClient:
    def get_control_methods(self, model_cls):
        assert model_cls is DeviceType
        return _resource_methods(
            list=lambda **kwargs: SimpleNamespace(
                results=[
                    SimpleNamespace(id=12, name="Alpha Sensor"),
                    SimpleNamespace(id=27, display_name="Beta Tracker"),
                ],
                count=2,
                next=None,
            )
        )


def test_resolve_control_model_class_returns_control_model():
    assert resolve_control_model_class("DeviceType") is DeviceType


def test_load_control_model_choices_builds_typed_choices():
    choices = load_control_model_choices(
        FakeLookupClient(),
        DeviceType,
        archived=False,
        ordering="name",
    )

    assert choices == [
        LookupChoice(
            id=12,
            label="Alpha Sensor (12)",
            search_values=("Alpha Sensor (12)", "12", "Alpha Sensor"),
            field_values={"display_name": None, "name": "Alpha Sensor"},
        ),
        LookupChoice(
            id=27,
            label="Beta Tracker (27)",
            search_values=("Beta Tracker (27)", "27", "Beta Tracker"),
            field_values={"display_name": "Beta Tracker", "name": None},
        ),
    ]


def test_resolve_resource_lookup_supports_ids_labels_aliases_and_errors():
    choices = [
        LookupChoice(id=12, label="Alpha Sensor (12)", search_values=("Alpha Sensor (12)", "12", "Alpha Sensor")),
        LookupChoice(id=27, label="Beta Tracker (27)", search_values=("Beta Tracker (27)", "27", "Beta Tracker")),
    ]

    assert resolve_resource_lookup(choices, "27", model_label="device type") == 27
    assert resolve_resource_lookup(choices, "Beta Tracker (27)", model_label="device type") == 27
    assert resolve_resource_lookup(choices, "Beta Tracker", model_label="device type") == 27

    with pytest.raises(Exception, match="No device type found"):
        resolve_resource_lookup(choices, "Missing", model_label="device type")

    duplicate_choices = [
        LookupChoice(id=1, label="Alpha (1)", search_values=("Alpha",)),
        LookupChoice(id=2, label="Alpha (2)", search_values=("Alpha",)),
    ]
    with pytest.raises(Exception, match="Multiple device types match"):
        resolve_resource_lookup(duplicate_choices, "Alpha", model_label="device type")


def test_resource_autocomplete_filters_results(monkeypatch):
    monkeypatch.setattr(
        "doover_cli.utils.crud.lookup.get_control_lookup_completion_client",
        lambda ctx: FakeLookupClient(),
    )

    items = resource_autocomplete(
        DeviceType,
        archived=False,
        ordering="name",
    )(
        click.Context(click.Command("archive")),
        [],
        "beta",
    )

    assert items == [("Beta Tracker (27)", "ID 27")]


def test_resource_autocomplete_returns_empty_list_for_expected_failures(monkeypatch):
    monkeypatch.setattr(
        "doover_cli.utils.crud.lookup.get_control_lookup_completion_client",
        lambda ctx: (_ for _ in ()).throw(ControlClientUnavailableError("test")),
    )

    items = resource_autocomplete(DeviceType)(click.Context(click.Command("test")), [], "")

    assert items == []


def test_resource_autocomplete_does_not_hide_unexpected_errors(monkeypatch):
    monkeypatch.setattr(
        "doover_cli.utils.crud.lookup.get_control_lookup_completion_client",
        lambda ctx: (_ for _ in ()).throw(ValueError("boom")),
    )

    with pytest.raises(ValueError, match="boom"):
        resource_autocomplete(DeviceType)(click.Context(click.Command("test")), [], "")
