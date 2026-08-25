"""Content-addressed cache for AudioObservations.

The distinction this module exists to hold (spec §16, and the bug that taught it): an
OBSERVATION is derived from the audio bytes alone, so content-addressing it is right. A
PROJECTION of that observation -- the characterisation a role and a caller's note produce --
is request-specific, so it must never be in this cache. `test_audio_card_is_not_cached.py`
holds the card side of the line; this module is the observation side.

The key is the bytes AND the logic that transformed them:

    sha256(audio bytes) | AUDIO_ANALYZER_VERSION | worker version | worker model ids

The versions are in the key because a cache keyed on its inputs but not on the transforming
logic serves stale results across a code change and looks correct -- the failure the main
analyser's ANALYZER_VERSION has now been needed for four times. Role, caller note, target
duration and request text are deliberately NOT in the key: they are projection inputs, and
putting them here would key the cache on content that contributes nothing to the observation.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from ..config import get_config
from .client import WorkerInfo
from .models import AUDIO_ANALYZER_VERSION, AudioObservation

log = logging.getLogger("h3ir.audio.cache")


def observation_key(sha256: str, worker: WorkerInfo) -> str:
    models = json.dumps(worker.models, sort_keys=True)
    return hashlib.sha256(
        f"{sha256}|{AUDIO_ANALYZER_VERSION}|{worker.version}|{models}".encode()
    ).hexdigest()[:24]


def _cache_path(key: str) -> Path:
    d = get_config().paths.cache_dir() / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def load_observation(sha256: str, worker: WorkerInfo) -> AudioObservation | None:
    """A bad entry is a miss, not an error -- the same rule the card cache keeps. The rewrite
    below costs one worker call; a crash here would cost the whole brief."""
    p = _cache_path(observation_key(sha256, worker))
    if not p.exists():
        return None
    try:
        obs = AudioObservation.from_dict(json.loads(p.read_text()))
    except Exception:  # noqa: BLE001
        return None
    if obs.sha256 != sha256:
        # The file claims to be an observation of different bytes. Trust nothing.
        return None
    return obs


def save_observation(obs: AudioObservation, worker: WorkerInfo) -> Path:
    p = _cache_path(observation_key(obs.sha256, worker))
    p.write_text(json.dumps(obs.to_dict(), indent=1, ensure_ascii=False))
    return p


# --------------------------------------------------------------------- fallback responses

# The fallback's ANSWER is byte-derived too -- same audio, same prompt version, same model --
# so it is cacheable on exactly those three. What is NOT cached is the decision to ask (the
# router's, role-dependent, per request) and the merge (request-scoped). This is how spec
# §16's "fallback model/version when fallback_used" is honoured without putting the role in
# any key: the role decides whether the cache is consulted, never what is stored under it.

def fallback_key(sha256: str, model: str) -> str:
    from .fallback import FALLBACK_PROTOCOL_VERSION
    return hashlib.sha256(
        f"{sha256}|{FALLBACK_PROTOCOL_VERSION}|{model}".encode()).hexdigest()[:24]


def load_fallback(sha256: str, model: str) -> dict | None:
    """A cached §11 payload, or None. Re-validated on load: a cache entry that no longer
    parses against the protocol is a miss, never a partial answer."""
    from .fallback import PROTOCOL_KEYS
    p = _cache_path("fb-" + fallback_key(sha256, model))
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict) or not set(payload) <= PROTOCOL_KEYS:
        return None
    return payload


def save_fallback(sha256: str, model: str, payload: dict) -> Path:
    p = _cache_path("fb-" + fallback_key(sha256, model))
    p.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    return p
