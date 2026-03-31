from doover_cli.apps.apps import ContainerRegistry
from doover_cli.utils.prompt import _normalize_choice_default


def test_normalize_choice_default_handles_enum_values():
    choices = [
        ContainerRegistry.GITHUB_INT.value,
        ContainerRegistry.GITHUB_OTHER.value,
    ]

    assert (
        _normalize_choice_default(ContainerRegistry.GITHUB_INT, choices)
        == ContainerRegistry.GITHUB_INT.value
    )


def test_normalize_choice_default_handles_multiple_values():
    choices = ["a", "b", "c"]

    assert _normalize_choice_default(("a", "c"), choices) == ["a", "c"]


def test_normalize_choice_default_leaves_choice_string_unchanged():
    choices = ["a", "b"]

    assert _normalize_choice_default("a", choices) == "a"
