"""AudioConfig: every host-specific audio value is an environment variable, read once.

Two properties matter. The DEFAULTS must describe a machine with no audio stack (disabled,
localhost URLs, placeholders that are never sent as credentials), because the default install
must behave exactly as it did before this existed. And the ENV VARS must actually land --
"a setting nobody sends is a setting nobody has" was the H3IR_LLM_KEY bug, and the audio
block doubles the surface it could happen on.
"""
from __future__ import annotations

import pytest

from h3ir.config import AudioConfig, Config

AUDIO_ENV = (
    "H3IR_AUDIO_ENABLED", "H3IR_AUDIO_URL", "H3IR_AUDIO_KEY", "H3IR_AUDIO_TIMEOUT",
    "H3IR_AUDIO_DIARIZATION", "H3IR_AUDIO_CLAP", "H3IR_AUDIO_DSP",
    "H3IR_AUDIO_FALLBACK", "H3IR_AUDIO_FALLBACK_URL", "H3IR_AUDIO_FALLBACK_MODEL",
    "H3IR_AUDIO_FALLBACK_KEY", "H3IR_AUDIO_FALLBACK_TIMEOUT",
    "H3IR_AUDIO_CONFIDENCE_THRESHOLD", "H3IR_AUDIO_EVENT_CONFIDENCE_THRESHOLD",
    "H3IR_AUDIO_CACHE", "H3IR_AUDIO_REQUIRED",
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in AUDIO_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_default_is_off_and_local(clean_env):
    cfg = AudioConfig()
    assert cfg.enabled is False, "the default install must not try to reach a worker"
    assert cfg.required is False, "and must never refuse a request over a missing worker"
    assert cfg.base_url == "http://127.0.0.1:50000"
    assert cfg.api_key == "not-needed"
    assert cfg.fallback_enabled is False, "the Omni fallback is gated by a router, not a default"
    assert cfg.cache_enabled is True
    assert (cfg.diarization, cfg.clap_enabled, cfg.dsp_enabled) == (True, True, True)
    assert cfg.confidence_threshold == pytest.approx(0.65)
    assert cfg.event_confidence_threshold == pytest.approx(0.55)


def test_every_documented_variable_lands(clean_env):
    clean_env.setenv("H3IR_AUDIO_ENABLED", "1")
    clean_env.setenv("H3IR_AUDIO_URL", "http://audio.internal:50000")
    clean_env.setenv("H3IR_AUDIO_KEY", "real-key")
    clean_env.setenv("H3IR_AUDIO_TIMEOUT", "45")
    clean_env.setenv("H3IR_AUDIO_DIARIZATION", "0")
    clean_env.setenv("H3IR_AUDIO_CLAP", "0")
    clean_env.setenv("H3IR_AUDIO_DSP", "0")
    clean_env.setenv("H3IR_AUDIO_FALLBACK", "1")
    clean_env.setenv("H3IR_AUDIO_FALLBACK_URL", "http://omni.internal:8001/v1")
    clean_env.setenv("H3IR_AUDIO_FALLBACK_MODEL", "Qwen2.5-Omni-3B-awq")
    clean_env.setenv("H3IR_AUDIO_FALLBACK_KEY", "omni-key")
    clean_env.setenv("H3IR_AUDIO_FALLBACK_TIMEOUT", "90")
    clean_env.setenv("H3IR_AUDIO_CONFIDENCE_THRESHOLD", "0.8")
    clean_env.setenv("H3IR_AUDIO_EVENT_CONFIDENCE_THRESHOLD", "0.4")
    clean_env.setenv("H3IR_AUDIO_CACHE", "0")
    clean_env.setenv("H3IR_AUDIO_REQUIRED", "1")

    cfg = AudioConfig()
    assert cfg.enabled is True and cfg.required is True
    assert cfg.base_url == "http://audio.internal:50000"
    assert cfg.api_key == "real-key"
    assert cfg.timeout_s == pytest.approx(45.0)
    assert (cfg.diarization, cfg.clap_enabled, cfg.dsp_enabled) == (False, False, False)
    assert cfg.fallback_enabled is True
    assert cfg.fallback_base_url == "http://omni.internal:8001/v1"
    assert cfg.fallback_model == "Qwen2.5-Omni-3B-awq"
    assert cfg.fallback_api_key == "omni-key"
    assert cfg.fallback_timeout_s == pytest.approx(90.0)
    assert cfg.confidence_threshold == pytest.approx(0.8)
    assert cfg.event_confidence_threshold == pytest.approx(0.4)
    assert cfg.cache_enabled is False


def test_an_empty_variable_means_unset_not_the_empty_string(clean_env):
    """A blank line in a sourced .env must not override a default with nothing -- the bug
    _env() exists to prevent."""
    clean_env.setenv("H3IR_AUDIO_URL", "")
    assert AudioConfig().base_url == "http://127.0.0.1:50000"


def test_config_carries_the_audio_block(clean_env):
    assert isinstance(Config().audio, AudioConfig)
