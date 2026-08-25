"""Worker-side settings. Everything host-specific about the Audio Worker lives here.

Separate process, separate settings module, same rule as the compiler's config.py: no other
file in this service reads the environment. The `AUDIO_WORKER_` prefix keeps these out of the
compiler's `H3IR_AUDIO_*` namespace, which describes how to REACH the worker, not how to RUN it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class WorkerSettings:
    # Bumped when the wire contract OR the analysis logic changes. The compiler keys its
    # observation cache on this plus the model ids, so a stale observation cannot survive a
    # worker upgrade -- the same discipline as ANALYZER_VERSION on the compiler side.
    version: str = "audio-worker-1"

    host: str = field(default_factory=lambda: _env("AUDIO_WORKER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("AUDIO_WORKER_PORT", 50000))

    # 200 MiB covers a 10-minute 320kbps stream several times over. The cap is enforced on
    # bytes actually received, not on a Content-Length a caller can lie in.
    max_upload_bytes: int = field(default_factory=lambda: _env_int(
        "AUDIO_WORKER_MAX_UPLOAD_BYTES", 200 * 1024 * 1024))
    # Long-form audio belongs to a different pipeline; H3 references are seconds-long.
    max_audio_seconds: float = field(default_factory=lambda: float(_env_int(
        "AUDIO_WORKER_MAX_AUDIO_SECONDS", 600)))

    # ModelScope ids, overridable for mirrors or local snapshots. Empty for a backend means
    # "not configured" and the backend reports unavailable rather than guessing.
    sensevoice_model: str = field(default_factory=lambda: _env(
        "AUDIO_WORKER_SENSEVOICE_MODEL", "iic/SenseVoiceSmall"))
    vad_model: str = field(default_factory=lambda: _env(
        "AUDIO_WORKER_VAD_MODEL", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"))
    speaker_model: str = field(default_factory=lambda: _env(
        "AUDIO_WORKER_SPEAKER_MODEL", "iic/speech_campplus_sv_zh_en_16k"))
    clap_model: str = field(default_factory=lambda: _env(
        "AUDIO_WORKER_CLAP_MODEL", "laion/clap-htsat-unfused"))
    model_dir: Path | None = field(default_factory=lambda: (
        Path(p) if (p := _env("AUDIO_WORKER_MODEL_DIR", "")) else None))
    device: str = field(default_factory=lambda: _env("AUDIO_WORKER_DEVICE", "cpu"))

    # Two embeddings closer than this are the same speaker. Cosine similarity, CAM++ space;
    # 0.65 is the middle of the usual operating band and it is a setting because the right
    # value is a property of the deployment's audio, not of this code.
    speaker_threshold: float = field(default_factory=lambda: float(_env(
        "AUDIO_WORKER_SPEAKER_THRESHOLD", "0.65")))


_SETTINGS: WorkerSettings | None = None


def get_settings() -> WorkerSettings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = WorkerSettings()
    return _SETTINGS


def set_settings(s: WorkerSettings) -> None:
    """Test seam."""
    global _SETTINGS
    _SETTINGS = s
