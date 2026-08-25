"""The AudioObservation contract: what the worker asserts, and how it survives a round trip.

The cache stores these as JSON, so the round trip IS the contract: an observation that
serialises differently after being reloaded is a cache entry whose hash moves under its own
key, and the failure mode is silent -- the bytes match, the answer is stale.
"""
from __future__ import annotations

import json

from h3ir.audio.models import (AUDIO_ANALYZER_VERSION, AudioEvent, AudioMusicProfile,
                               AudioObservation, AudioRhythm, AudioSignalFacts,
                               AudioVoiceProfile, TimedSpeech)

from fake_audio_worker import sample_observation


def _full_observation() -> AudioObservation:
    obs = sample_observation()
    obs.events = [AudioEvent(start_s=4.73, end_s=5.04, label="metallic impact",
                             confidence=0.87, source="clap")]
    obs.voice = AudioVoiceProfile(speaker_count=1, pitch_class="low", energy="soft",
                                  pace="slow", delivery="tense", emotions=["fearful"])
    obs.music = AudioMusicProfile(present=True, genres=["dark ambient"],
                                  instruments=["synth pad"], mood=["tense"], tempo_bpm=72.4)
    obs.signal.silence_regions = [(2.9, 3.4)]
    obs.semantic_summary = "a tense whispered warning over a drone"
    obs.semantic_facts = ["the impact lands just after the line ends"]
    obs.model_ids = {"sensevoice": "SenseVoiceSmall"}
    obs.confidence = 0.91
    obs.fallback_used = True
    obs.partial = True
    return obs


def test_a_full_observation_round_trips_through_json_unchanged():
    obs = _full_observation()
    text = json.dumps(obs.to_dict(), sort_keys=True, ensure_ascii=False)
    back = AudioObservation.from_dict(json.loads(text))
    assert back == obs
    assert back.hash() == obs.hash(), "a reload must not move the hash under its own key"


def test_silence_regions_come_back_as_tuples_not_lists():
    """JSON has no tuples. A region that reloads as a list still COMPARES unequal to a tuple
    and would drift the serialised form on every save/load cycle."""
    back = AudioObservation.from_dict(sample_observation().to_dict() | {
        "signal": {**sample_observation().signal.__dict__, "silence_regions": [[1.0, 2.0]]}})
    assert back.signal.silence_regions == [(1.0, 2.0)]
    assert isinstance(back.signal.silence_regions[0], tuple)


def test_the_minimal_observation_is_just_bytes_and_signal():
    """A worker that ran only DSP still produces a valid contract object."""
    obs = AudioObservation(sha256="b" * 64, signal=AudioSignalFacts(duration_s=8.52))
    assert obs.analyzer_version == AUDIO_ANALYZER_VERSION
    assert AudioObservation.from_dict(obs.to_dict()) == obs


def test_the_hash_tracks_content_and_ignores_nothing():
    a, b = sample_observation(), sample_observation()
    assert a.hash() == b.hash()
    b.rhythm.tempo_bpm = 140.0
    assert a.hash() != b.hash(), "a changed fact must change the hash"


def test_partial_and_fallback_flags_are_first_class_fields():
    """A worker that half-failed and an observation the fallback touched must both be visible
    in the contract, not inferable later from a log."""
    obs = _full_observation()
    raw = obs.to_dict()
    assert raw["partial"] is True and raw["fallback_used"] is True
    assert AudioObservation.from_dict(raw).partial is True
