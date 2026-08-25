"""Provenance (spec §24): every characterised <Audio N> gets a record saying why the IR may
say what it says -- which bytes, which analyser chain, whether the fallback touched it, and
under which role it was projected. That record is A25's traceability made structural.

Compiled for real with the model off (llm=False): the assertions read the artifact a caller
receives, not a hand-built stand-in.
"""
from __future__ import annotations

from h3ir import compile as C
from h3ir.audio.models import (AudioMusicProfile, AudioObservation, AudioRhythm,
                               AudioSignalFacts)
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Role


class _Backend:
    class cfg:
        model = "test-model"

    def require_available(self):
        pass

    def server_version(self):
        return "test"

    def close(self):
        pass


def _track(*, fallback_used: bool = False) -> AudioObservation:
    obs = AudioObservation(
        sha256="b" * 64,
        signal=AudioSignalFacts(duration_s=6.0, sample_rate=48000, channels=2),
        music=AudioMusicProfile(present=True, genres=["electronic"],
                                instruments=["synth bass"], mood=["driving"]),
        rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.94,
                           beat_times_s=[0.47, 0.94, 1.41],
                           downbeat_times_s=[1.90]),
    )
    # The identity chain the worker's /health answered with, plus the worker's own version
    # (observer.py sets the audio_worker key).
    obs.model_ids = {"audio_worker": "audio-worker-1", "dsp": "dsp",
                     "speech": "iic/SenseVoiceSmall+iic/fsmn-vad+iic/campplus",
                     "clap": "laion/clap-htsat-unfused"}
    obs.fallback_used = fallback_used
    return obs


def _compile_with(card: AssetCard | None) -> C.IRDocument:
    brief = Brief(intent="a car commercial with a driving beat", seconds=8.0,
                  assets=[AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="b" * 64,
                                   seconds=6.0, note="the client's title track")])
    cards = {"b" * 64: card} if card else {}
    real_analyse = C.analyse_all
    C.analyse_all = lambda *a, **k: cards
    try:
        return C.compile_brief(brief, backend=_Backend(), llm=False)
    finally:
        C.analyse_all = real_analyse


def test_every_characterised_audio_gets_a_provenance_record():
    doc = _compile_with(AssetCard(sha256="b" * 64, kind=AssetKind.AUDIO,
                                  audio_observation=_track()))
    rec = (doc.provenance.get("audio") or {}).get("<Audio 1>")
    assert rec, "a characterised audio asset must be traceable (A25)"
    assert rec["observation_hash"] == _track().hash()
    assert rec["audio_worker"] == "audio-worker-1"
    assert rec["sensevoice_model"].startswith("iic/SenseVoiceSmall")
    assert rec["clap_model"] == "laion/clap-htsat-unfused"
    assert rec["projection_role"] == "bgm"
    # The full identity chain travels too: the named keys are the readable index into it.
    assert rec["models"]["speech"].count("+") == 2


def test_a_fallback_supplement_is_named_with_its_model():
    doc = _compile_with(AssetCard(sha256="b" * 64, kind=AssetKind.AUDIO,
                                  audio_observation=_track(fallback_used=True)))
    rec = doc.provenance["audio"]["<Audio 1>"]
    assert rec["fallback_used"] is True
    assert rec["fallback_model"], "a fallback-touched observation must name the fallback model"


def test_no_fallback_means_no_fallback_model_claimed():
    doc = _compile_with(AssetCard(sha256="b" * 64, kind=AssetKind.AUDIO,
                                  audio_observation=_track()))
    rec = doc.provenance["audio"]["<Audio 1>"]
    assert rec["fallback_used"] is False
    assert "fallback_model" not in rec


def test_uncharacterised_audio_gets_no_audio_block():
    """The legacy path (no observation) must not record a provenance block it cannot fill:
    'not stated', never 'no audio'."""
    doc = _compile_with(AssetCard(sha256="b" * 64, kind=AssetKind.AUDIO))
    assert not doc.provenance.get("audio")
