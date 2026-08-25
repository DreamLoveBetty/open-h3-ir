"""HTTP client for the Audio Worker.

The worker is a separate process owning the heavy dependencies (SenseVoice, FSMN-VAD, CAM++,
CLAP, torch) so this package keeps its dependency list at HTTP + JSON. The compiler and the
worker are assumed NOT to share a filesystem in general, the same assumption the ComfyUI
client makes: audio crosses as bytes in a multipart POST, never as a path the worker is asked
to open.

Two error families, kept apart because they need different answers:

  * AudioWorkerUnavailable -- nothing answered, or the answer never arrived. The degraded
    path is legal here: the request can still be honoured with typed metadata, exactly as
    every brief was before audio analysis existed.
  * AudioWorkerBadResponse -- something answered and the answer cannot be trusted: an HTTP
    error, malformed JSON, a body that does not parse into an AudioObservation. Degrading
    here too, but the message must say the worker answered badly, because "unreachable" and
    "answered nonsense" are debugged in different places.

Neither is ever silently swallowed into a fake empty observation (rule: a partial answer must
be marked, not laundered into a complete-looking one).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..config import AudioConfig
from .models import AudioObservation

log = logging.getLogger("h3ir.audio.client")


class AudioWorkerError(RuntimeError):
    """Base class for everything that can go wrong between here and an observation."""


class AudioWorkerUnavailable(AudioWorkerError):
    """Connect refused, DNS, timeout: the worker did not answer."""


class AudioWorkerBadResponse(AudioWorkerError):
    """The worker answered, and the answer cannot be used."""


@dataclass(frozen=True)
class WorkerInfo:
    """Who produced an observation. Part of the cache key AND of provenance: a cached
    observation must stop being served when the models that produced it change, and an IR
    sentence must be able to say which analyser it traces to."""

    version: str = ""
    models: dict[str, str] = field(default_factory=dict)


class AudioWorkerClient:
    """One worker, reached over HTTP. Thin on purpose: all semantics live in the observation
    contract, so this class is transport and error mapping and nothing else.

    `transport` is the test seam: httpx's own MockTransport, so the wire shape (multipart
    fields, headers, error mapping) is tested against the real HTTP stack without a socket."""

    def __init__(self, cfg: AudioConfig, *, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def _headers(self) -> dict[str, str]:
        # The "not-needed" placeholder means "no header", never a credential -- the bug this
        # copies from backend._headers: sending the placeholder to a server with auth on gets
        # a 401 that names the wrong problem.
        if self.cfg.api_key and self.cfg.api_key != "not-needed":
            return {"Authorization": f"Bearer {self.cfg.api_key}"}
        return {}

    def health(self) -> WorkerInfo:
        """GET /health. The answer identifies the worker build, which is what makes the
        observation cache key honest: `version` and `models` are the transforming logic, and a
        cache keyed on the bytes alone would serve stale observations across a model swap --
        the failure ANALYZER_VERSION exists to prevent, one process over."""
        url = f"{self.cfg.base_url.rstrip('/')}/health"
        try:
            with self._client(min(self.cfg.timeout_s, 10.0)) as http:
                resp = http.get(url, headers=self._headers())
        except httpx.TransportError as e:
            raise AudioWorkerUnavailable(f"audio worker at {self.cfg.base_url} did not answer: {e}") from e
        if resp.status_code != 200:
            raise AudioWorkerBadResponse(
                f"audio worker health check returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}")
        try:
            raw = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise AudioWorkerBadResponse(f"audio worker health is not JSON: {e}") from e
        if not isinstance(raw, dict):
            raise AudioWorkerBadResponse("audio worker health is not a JSON object")
        return WorkerInfo(version=str(raw.get("version", "")),
                          models={str(k): str(v) for k, v in (raw.get("models") or {}).items()})

    def analyse(self, path: str | Path, *, diarization: bool = True, clap: bool = True,
                dsp: bool = True) -> tuple[AudioObservation, WorkerInfo]:
        """POST /v1/audio/analyze with the file as multipart bytes.

        Returns the observation AND the worker's identity, because the response body is where
        the per-analysis model ids live and the cache key needs both sides.
        """
        p = Path(path)
        url = f"{self.cfg.base_url.rstrip('/')}/v1/audio/analyze"
        data = {
            "enable_diarization": "true" if diarization else "false",
            "enable_clap": "true" if clap else "false",
            "enable_dsp": "true" if dsp else "false",
        }
        try:
            with p.open("rb") as fh:
                files = {"file": (p.name, fh, "application/octet-stream")}
                with self._client(self.cfg.timeout_s) as http:
                    resp = http.post(url, data=data, files=files, headers=self._headers())
        except httpx.TransportError as e:
            raise AudioWorkerUnavailable(
                f"audio worker at {self.cfg.base_url} did not answer: {e}") from e
        except OSError as e:
            # The file vanished or cannot be read -- the caller's problem, not the worker's.
            raise AudioWorkerError(f"cannot read audio file {p}: {e}") from e
        if resp.status_code != 200:
            raise AudioWorkerBadResponse(
                f"audio worker returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            raw = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise AudioWorkerBadResponse(f"audio worker response is not JSON: {e}") from e
        if not isinstance(raw, dict):
            raise AudioWorkerBadResponse("audio worker response is not a JSON object")

        info = WorkerInfo(version=str(raw.get("version", "")),
                          models={str(k): str(v) for k, v in (raw.get("models") or {}).items()})
        # A partial response must say so. The observation carries the flag rather than the
        # client raising, because partial facts are still facts -- the fallback router is the
        # one that decides they are not enough.
        partial = bool(raw.get("incomplete") or raw.get("partial"))
        # Wire-only fields: the worker's own identity and the top-level `duration_s`
        # convenience (a duplicate of signal.duration_s) are not observation fields.
        body = {k: v for k, v in raw.items()
                if k not in ("version", "models", "incomplete", "partial", "duration_s")}
        body.setdefault("sha256", "")
        body.setdefault("signal", {})
        try:
            obs = AudioObservation.from_dict(body)
        except (TypeError, KeyError) as e:
            raise AudioWorkerBadResponse(
                f"audio worker response does not parse as an AudioObservation: {e}") from e
        obs.partial = obs.partial or partial
        if info.models and not obs.model_ids:
            obs.model_ids = dict(info.models)
        return obs, info
