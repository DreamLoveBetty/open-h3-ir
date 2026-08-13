"""OpenH3-IR nodes for ComfyUI.

This directory is the whole node pack. Copy or link it into ComfyUI's `custom_nodes` under a name of
your choosing and restart ComfyUI. Installation and wiring are in README.md beside this file.

Nothing here imports the `h3ir` package. The nodes speak to a running OpenH3-IR service over HTTP, so
the compiler's dependencies can never collide with the ones ComfyUI needs, and the service is free to
live on another machine.

The node registration lives in `nodes.py` as a `comfy_entrypoint`, which is ComfyUI's current way of
declaring nodes and the same one the built-in MiniMax H3 nodes use. It is imported lazily below so
that this package stays importable outside ComfyUI: the parts worth testing do not need a canvas, and
`h3ir_client` has no ComfyUI imports at all.
"""
from __future__ import annotations


async def comfy_entrypoint():
    """Hand ComfyUI the node list. Imported here rather than at module scope so a machine without
    ComfyUI can still import this package to test the parts that do not need it."""
    from .nodes import comfy_entrypoint as real
    return await real()


__all__ = ["comfy_entrypoint"]
