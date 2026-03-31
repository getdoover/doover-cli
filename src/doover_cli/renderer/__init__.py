from enum import Enum
from ._base import RendererBase
from ._json import JsonRenderer
from ._basic import BasicRenderer
from ._default import DefaultRenderer


class Renderer(str, Enum):
    basic = "basic"
    json = "json"
    default = "default"
    # rich = "rich"
    # table = "table"


def setup_renderer(renderer: Renderer) -> RendererBase:
    if renderer is Renderer.json:
        return JsonRenderer()
    if renderer is Renderer.default:
        return DefaultRenderer()
    return BasicRenderer()


__all__ = [
    "setup_renderer",
    "Renderer",
    "RendererBase",
    "JsonRenderer",
    "DefaultRenderer",
]
