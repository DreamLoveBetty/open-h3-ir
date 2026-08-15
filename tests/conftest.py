"""Test-session configuration.

The registry tests read the example LoRA that ships in this repo, so the tests point
`H3IR_LORA_DIRS` at it explicitly rather than inheriting whatever the machine happens to have.
Set before any `get_config()` call, because the config is built once and cached.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The `comfyui` package lives at the repo root and is imported by name in its tests. `python -m
# pytest` puts the root on sys.path as a side effect; the bare `pytest` script (which is what CI
# runs) does not, and the whole comfyui suite dies on collection. Pinned here so every invocation
# is the same invocation.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("H3IR_LORA_DIRS", str(REPO / "loras"))
