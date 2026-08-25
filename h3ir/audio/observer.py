"""The audio observer: the one entry point from the compiler into the audio stack.

`observe_audio` is where the cache, the worker and the fallback meet. It owns no analysis
logic itself -- the worker answers the questions, the cache decides whether the question needs
asking, the router decides whether the deterministic answer needs a semantic supplement, and
the merge applies it. Later phases were meant to hang off this seam without the compiler ever
learning their names; the fallback is the first one that did.

Returns (observation, findings): the findings are the fallback stage's report -- an off-protocol
payload, an attempted deterministic overwrite (A26), a fallback that failed. They travel on the
AssetCard and surface through the plan's audio context, so a caller can see that a supplement
was refused rather than never learning it was attempted.
"""
from __future__ import annotations

import logging

from ..config import Config
from ..models import AssetRef, Finding
from .cache import (load_fallback, load_observation, save_fallback, save_observation)
from .client import AudioWorkerClient, WorkerInfo
from .models import AudioObservation

log = logging.getLogger("h3ir.audio.observer")


def observe_audio(ref: AssetRef, cfg: Config, *, client: AudioWorkerClient | None = None,
                  fallback_client=None, use_cache: bool = True,
                  ) -> tuple[AudioObservation, list[Finding]]:
    """Observe one audio asset. Raises AudioWorkerError on WORKER failure -- the CALLER decides
    whether degradation is legal, because only the caller knows the `required` setting and
    only it can produce the legacy card the degraded path falls back to. The FALLBACK is the
    opposite contract: it is a supplement over an already-complete observation, so its failure
    degrades to "no supplement" with a finding, never to an exception.

    `client` / `fallback_client` are test seams: anything with the right method shape will do,
    which is how the mock worker and the fake Omni get in without a socket.
    """
    if not ref.path:
        raise ValueError("observe_audio needs a readable path; no-path assets are the "
                         "legacy metadata path's job")
    client = client or AudioWorkerClient(cfg.audio)
    # Health first, and not only as a liveness check: the observation cache is keyed on the
    # worker's version and model ids, so there is no honest cache lookup without them. The
    # cost on a cache hit is one local HTTP round trip, well under the 100ms budget.
    info: WorkerInfo = client.health()

    obs: AudioObservation | None = None
    if use_cache and cfg.audio.cache_enabled:
        obs = load_observation(ref.sha256, info)
        if obs is not None:
            log.info("audio observation cache hit %s", ref.sha256[:12])

    if obs is None:
        obs, info = client.analyse(ref.path, diarization=cfg.audio.diarization,
                                   clap=cfg.audio.clap_enabled, dsp=cfg.audio.dsp_enabled)
        # The worker saw bytes; WE know what those bytes hash to. The caller's sha wins,
        # because it is the identity every other stage already agrees on.
        obs.sha256 = ref.sha256
        if not obs.model_ids and info.models:
            obs.model_ids = dict(info.models)
        # The worker's own version rides in model_ids so §24 provenance can name the build that
        # produced the facts; the cache key already contains it, so a cached entry is always
        # self-describing about its origin.
        obs.model_ids.setdefault("audio_worker", info.version)
        if use_cache and cfg.audio.cache_enabled:
            save_observation(obs, info)

    return _maybe_supplement(obs, ref, cfg, fallback_client=fallback_client,
                             use_cache=use_cache)


def _maybe_supplement(obs: AudioObservation, ref: AssetRef, cfg: Config, *,
                      fallback_client, use_cache: bool,
                      ) -> tuple[AudioObservation, list[Finding]]:
    """The fallback stage: router decides, cache answers or the client asks, merge applies.

    Runs AFTER the observation cache, on purpose in both directions: the cached object is the
    pre-merge worker truth (byte-keyed, role-free), and the router's answer is role-dependent
    and therefore computed per request even when the observation itself was a cache hit.
    """
    findings: list[Finding] = []
    if not cfg.audio.fallback_enabled:
        return obs, findings

    from .router import decide_fallback
    decision = decide_fallback(obs, ref.role, caller_note=ref.note or "",
                               confidence_threshold=cfg.audio.confidence_threshold,
                               event_confidence_threshold=cfg.audio.event_confidence_threshold)
    if not decision.use_fallback:
        return obs, findings
    log.info("audio fallback triggered for %s: %s", ref.sha256[:12], "; ".join(decision.reasons))

    model = cfg.audio.fallback_model
    payload = load_fallback(ref.sha256, model) if use_cache and cfg.audio.cache_enabled else None
    if payload is None:
        fallback_client = fallback_client or _default_fallback_client(cfg)
        try:
            payload = fallback_client.observe(ref.path)
        except Exception as e:  # noqa: BLE001 -- protocol and transport failures alike
            from .fallback import FallbackPayloadError
            from .merge import deterministic_overwrite_attempt
            if isinstance(e, FallbackPayloadError):
                a26 = deterministic_overwrite_attempt(e.extra_keys)
                if a26 is not None:
                    findings.append(a26)
                else:
                    findings.append(Finding(
                        "A28-audio-fallback-off-protocol", "WARN",
                        f"the fallback model's reply was not the §11 protocol ({e}); the "
                        "deterministic observation shipped without a supplement"))
            else:
                findings.append(Finding(
                    "A28-audio-fallback-off-protocol", "WARN",
                    f"the audio fallback failed ({type(e).__name__}: {e}); the deterministic "
                    "observation shipped without a supplement"))
            return obs, findings
        if use_cache and cfg.audio.cache_enabled:
            save_fallback(ref.sha256, model, payload)

    from .merge import merge_fallback
    merged, merge_findings = merge_fallback(obs, payload)
    if merged.fallback_used:
        merged.model_ids = {**merged.model_ids, "fallback": model}
    return merged, findings + merge_findings


def _default_fallback_client(cfg: Config):
    from .fallback import FallbackClient
    return FallbackClient(cfg.audio)
