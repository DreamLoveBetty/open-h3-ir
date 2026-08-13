"""OpenH3-IR nodes for ComfyUI.

This directory is the whole node pack. Copy or link it into ComfyUI's `custom_nodes` under a name of
your choosing and restart ComfyUI. Installation and wiring are in README.md beside this file.

Nothing here imports the `h3ir` package. The nodes speak to a running OpenH3-IR service over HTTP, so
the compiler's dependencies can never collide with the ones ComfyUI needs, and the service is free to
live on another machine.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
