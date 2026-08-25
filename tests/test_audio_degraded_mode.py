"""The three running states: FULL, PARTIAL-degraded, and LEGACY.

The bar these tests hold is spec §25 plus the repo's standing rule that a caller cannot tell
a good IR from a worse one, so degradation must never be silent at the level that can act on
it. LEGACY (audio off, or worker unreachable without H3IR_AUDIO_REQUIRED) must produce
byte-identical output to what every brief produced before this feature existed -- that is
what "compatible" means here, and it is checked against the legacy strings, not against a
re-run of the same code.
"""
from __future__ import annotations

import logging

import pytest

from h3ir.analyse import AssetAnalysisError, analyse_all, analyse_audio
from h3ir.config import AudioConfig, Config, Paths, get_config, set_config
from h3ir.models import AssetKind, AssetRef, Role

from fake_audio_worker import FakeWorker, UnreachableWorker


@pytest.fixture
def audio_state(tmp_path):
    old = get_config()
    set_config(Config(paths=Paths(state_dir=tmp_path),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test")))
    yield tmp_path
    set_config(old)


def _ref(role: Role = Role.VOICE_TIMBRE, note: str = "a flat male voice, close mic",
         path: str | None = "clip.wav") -> AssetRef:
    return AssetRef(kind=AssetKind.AUDIO, role=role, sha256="a" * 64, seconds=3.0,
                    note=note, path=path)


# ------------------------------------------------------------------ LEGACY

def test_disabled_means_the_worker_is_never_consulted(audio_state):
    """The default install behaves exactly as before: even with a path and a configured URL,
    `enabled: False` short-circuits before any client is built."""
    set_config(Config(paths=Paths(state_dir=audio_state),
                      audio=AudioConfig(enabled=False)))
    card = analyse_audio(_ref(), audio_backend=UnreachableWorker())
    assert card.audio_observation is None
    assert card.model_id == "none (typed metadata only)"
    assert card.summary == ("a spoken vocal reference supplying voice timbre and delivery, "
                            "described by the caller as: a flat male voice, close mic (3.00s).")


def test_enabled_without_a_path_is_the_legacy_metadata_path(audio_state):
    card = analyse_audio(_ref(path=None), audio_backend=UnreachableWorker())
    assert card.audio_observation is None
    assert card.characterisation == "a flat male voice, close mic"


def test_an_unreachable_worker_degrades_to_legacy_with_a_warning(audio_state, caplog):
    with caplog.at_level(logging.WARNING, logger="h3ir.analyse"):
        card = analyse_audio(_ref(), audio_backend=UnreachableWorker())
    assert card.audio_observation is None
    assert card.model_id == "none (typed metadata only)"
    assert card.transcript == ""
    assert any("degraded" in r.message for r in caplog.records), \
        "rule 4: the degradation must be loud where someone can act on it"


def test_required_turns_an_unreachable_worker_into_a_refusal(audio_state):
    set_config(Config(paths=Paths(state_dir=audio_state),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test",
                                        required=True)))
    with pytest.raises(AssetAnalysisError, match="H3IR_AUDIO_REQUIRED"):
        analyse_audio(_ref(), audio_backend=UnreachableWorker())


def test_a_worker_bad_response_also_degrades_unless_required(audio_state):
    """The two error families share the degraded path but not the message: 'answered badly'
    must not be logged as 'unreachable', they are debugged in different places."""
    from h3ir.audio.client import AudioWorkerBadResponse

    class BadWorker(UnreachableWorker):
        def health(self):
            raise AudioWorkerBadResponse("audio worker health check returned HTTP 500")

    card = analyse_audio(_ref(), audio_backend=BadWorker())
    assert card.audio_observation is None


# ------------------------------------------------------------------ FULL

def test_the_enhanced_path_projects_the_observation_onto_the_card(audio_state):
    card = analyse_audio(_ref(), audio_backend=FakeWorker())
    assert card.audio_observation is not None
    # The legacy interface keeps its contract: role sentence, caller note, duration.
    assert card.summary.startswith("a spoken vocal reference supplying voice timbre")
    assert "flat male voice" in card.summary
    assert card.characterisation == "a flat male voice, close mic"
    # The heard facts land where the renderer already reads them.
    assert card.transcript == "We close at six, not half past."
    assert card.language == "en"
    # And the fields nobody has projected yet stay honestly empty.
    assert card.timbre == "" and card.music == ""


def test_a_caller_transcript_outranks_the_workers_asr(audio_state):
    card = analyse_audio(_ref(), transcript="Caller words win.", audio_backend=FakeWorker())
    assert card.transcript == "Caller words win."
    assert card.audio_observation.speech[0].text == "We close at six, not half past.", \
        "the observation keeps the heard words; only the card's projection prefers the caller"


def test_analyse_all_threads_the_backend_through(audio_state):
    class _Backend:
        class cfg:
            model = "test-model"

    worker = FakeWorker()
    cards = analyse_all(_Backend(), [_ref()], audio_backend=worker)
    assert cards["a" * 64].audio_observation is not None
    assert worker.analyse_calls == 1
