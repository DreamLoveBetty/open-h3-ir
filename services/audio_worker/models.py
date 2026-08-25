"""The wire shapes the worker answers with, and the builder that enforces them.

The compiler's `AudioObservation.from_dict` is STRICT: a key it does not know is a bad
response, not a tolerated extra. So the response is assembled here and only here, from an
explicit allow-list -- a backend that starts returning a new field breaks the compiler on the
other side of an HTTP boundary, and that failure should happen in this file's tests, not in a
user's compile.
"""
from __future__ import annotations

from typing import Any

# The exact top-level keys the compiler's client accepts. "version"/"models"/"duration_s"
# are wire conveniences it strips before parsing; the rest map onto AudioObservation fields.
WIRE_KEYS = ("version", "models", "duration_s", "incomplete",
             "signal", "speech", "events", "voice", "music", "rhythm")


def build_response(*, version: str, models: dict[str, str], duration_s: float,
                   signal: dict[str, Any], speech: list[dict[str, Any]],
                   events: list[dict[str, Any]], voice: dict[str, Any],
                   music: dict[str, Any], rhythm: dict[str, Any],
                   incomplete: bool = False) -> dict[str, Any]:
    """Assemble the one response shape. Every key is named here; nothing else may leak out."""
    out = {
        "version": version,
        "models": dict(models),
        "duration_s": duration_s,
        "incomplete": bool(incomplete),
        "signal": signal,
        "speech": speech,
        "events": events,
        "voice": voice,
        "music": music,
        "rhythm": rhythm,
    }
    assert set(out) <= set(WIRE_KEYS), "a new wire key must be added deliberately, in one place"
    return out
