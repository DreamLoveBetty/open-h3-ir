"""The audio observer: the one entry point from the compiler into the audio stack.

`observe_audio` is where the cache and the worker meet. It owns no analysis logic itself --
the worker answers the questions, the cache decides whether the question needs asking, and
this function is the seam that later phases (DSP merge, the confidence router, the Omni
fallback) hang off without the compiler ever learning their names.
"""
from __future__ import annotations

import logging

from ..config import Config
from ..models import AssetRef
from .cache import load_observation, save_observation
from .client import AudioWorkerClient, WorkerInfo
from .models import AudioObservation

log = logging.getLogger("h3ir.audio.observer")


def observe_audio(ref: AssetRef, cfg: Config, *, client: AudioWorkerClient | None = None,
                  use_cache: bool = True) -> AudioObservation:
    """Observe one audio asset. Raises AudioWorkerError on failure -- the CALLER decides
    whether degradation is legal, because only the caller knows the `required` setting and
    only it can produce the legacy card the degraded path falls back to.

    `client` is a test seam: anything with `health()` and `analyse()` in the shape of
    AudioWorkerClient will do, which is how the mock worker gets in without a socket.
    """
    if not ref.path:
        raise ValueError("observe_audio needs a readable path; no-path assets are the "
                         "legacy metadata path's job")
    client = client or AudioWorkerClient(cfg.audio)
    # Health first, and not only as a liveness check: the observation cache is keyed on the
    # worker's version and model ids, so there is no honest cache lookup without them. The
    # cost on a cache hit is one local HTTP round trip, well under the 100ms budget.
    info: WorkerInfo = client.health()

    if use_cache and cfg.audio.cache_enabled:
        hit = load_observation(ref.sha256, info)
        if hit is not None:
            log.info("audio observation cache hit %s", ref.sha256[:12])
            return hit

    obs, info = client.analyse(ref.path, diarization=cfg.audio.diarization,
                               clap=cfg.audio.clap_enabled, dsp=cfg.audio.dsp_enabled)
    # The worker saw bytes; WE know what those bytes hash to. The caller's sha wins, because
    # it is the identity every other stage already agrees on.
    obs.sha256 = ref.sha256
    if not obs.model_ids and info.models:
        obs.model_ids = dict(info.models)

    if use_cache and cfg.audio.cache_enabled:
        save_observation(obs, info)
    return obs
