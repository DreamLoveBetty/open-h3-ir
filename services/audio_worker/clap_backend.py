"""CLAP event / texture semantics. Phase D: the socket exists, the model does not.

Why a stub that says so rather than an absent file: the app asks this backend whether it can
run, and "no" must be an honest, structured answer that ends up as `incomplete: true` on the
wire -- not an ImportError a handler has to sniff out of a traceback. When the real backend
lands it keeps this interface: sliding-window plus onset-driven classification, returning
labelled time windows with confidence, never one label for the whole file.
"""
from __future__ import annotations

from .dsp_backend import BackendUnavailable


class CLAPBackend:
    name = "clap"

    def __init__(self, settings):
        self.settings = settings

    def available(self) -> tuple[bool, str]:
        return False, "CLAP lands with Phase D (spec §33, commit 9); event semantics come " \
                      "from SenseVoice's coarse tags until then"

    def classify_windows(self, wav16k, *, onsets: list[float] | None = None) -> list[dict]:
        raise BackendUnavailable("CLAP backend is not built yet (Phase D)")
