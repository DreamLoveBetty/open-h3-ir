"""ComfyUI entry point for when this repository is installed whole as a node pack.

ComfyUI Manager installs a pack by cloning the entire repository into `custom_nodes` and importing
its top level, so this file is the one-level bridge to the actual pack in `comfyui/`: it re-exports
exactly what ComfyUI looks for and nothing else. The copy-or-link install in comfyui/README.md keeps
working and never reads this file, and nothing in `h3ir` imports it either.

The imports below name the pack both ways because this file lives two lives. Under ComfyUI it is a
package named after the cloned folder, and the package-qualified form is the only correct one. Under
pytest's collection the same file is imported once as a bare top-level module with no parent package,
where only the absolute form can resolve; the repo root is on sys.path there, so `comfyui` is the
same folder either way.
"""
from __future__ import annotations

import importlib

_PREFIX = __package__ + "." if __package__ else ""

web_api = importlib.import_module(_PREFIX + "comfyui.web_api")  # registers the pack's HTTP routes

WEB_DIRECTORY = "comfyui/web"


async def comfy_entrypoint():
    """Hand ComfyUI the node list from the real pack one level down."""
    nodes = importlib.import_module(_PREFIX + "comfyui.nodes")
    return await nodes.comfy_entrypoint()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
