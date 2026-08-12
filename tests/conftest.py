"""Test-session configuration.

The registry tests read the example LoRA that ships in this repo, so the tests point
`H3IR_LORA_DIRS` at it explicitly rather than inheriting whatever the machine happens to have.
Set before any `get_config()` call, because the config is built once and cached.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ.setdefault("H3IR_LORA_DIRS", str(REPO / "loras"))
