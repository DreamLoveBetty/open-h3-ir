"""The repository installs whole as a ComfyUI node pack.

ComfyUI Manager's git-clone install drops the entire repository into `custom_nodes` and imports its
top level, exactly the way `spec_from_file_location` on an `__init__.py` does. Measured 2026-08-15
before the root bridge existed: the clone landed the pack's `__init__` one level too deep, ComfyUI
found nothing at the top, and the install produced zero nodes. Manager also pip-installs a cloned
pack's requirements.txt automatically, and ours used to say `-e .[dev]`, which would have pushed the
whole compiler plus pytest into every user's ComfyUI. Both halves of the fix get a control here.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_repo_root_as_comfyui_does():
    """ComfyUI's loader in miniature: the directory's __init__.py becomes a package."""
    spec = importlib.util.spec_from_file_location("open_h3_ir_clone_test", REPO / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        # the module stays importable for the duration of the test that asked for it, but the
        # fake clone must not leak into the rest of the suite
        sys.modules.pop(spec.name, None)
    return module


def test_the_repo_root_presents_the_pack_contract():
    module = _load_repo_root_as_comfyui_does()
    assert asyncio.iscoroutinefunction(module.comfy_entrypoint)
    web = REPO / module.WEB_DIRECTORY
    assert web.is_dir(), f"WEB_DIRECTORY points at nothing: {module.WEB_DIRECTORY}"
    assert list(web.glob("*.js")), "the served web folder has no frontend code in it"


def test_requirements_txt_stays_directive_free():
    """Manager runs `pip install -r requirements.txt` on every install of the cloned pack. The
    nodes need nothing installed, so the file must hold comments only. A directive reappearing
    here means every node user gets the compiler forced into ComfyUI's Python."""
    lines = (REPO / "requirements.txt").read_text().splitlines()
    directives = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    assert directives == [], f"requirements.txt gained install directives: {directives}"
