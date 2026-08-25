"""The fallback router (spec §10, §28.3): rule-scored, and silent when it should be.

The "不应 fallback" half of the spec is as load-bearing as the triggers: a gate that fires on
clean ASR, a reliable beat grid or a plain BGM copy is a default path wearing a router's coat.
Every test here names which side of that line it holds.
"""
from __future__ import annotations

from h3ir.audio.models import (AudioEvent, AudioMusicProfile, AudioObservation,
                               AudioRhythm, AudioSignalFacts, AudioVoiceProfile,
                               TimedSpeech)
from h3ir.audio.router import caller_asked_for_detail, decide_fallback
from h3ir.models import Role


def _obs(**kw) -> AudioObservation:
    base = dict(sha256="f" * 64, signal=AudioSignalFacts(duration_s=6.0))
    base.update(kw)
    return AudioObservation(**base)


# ---------------------------------------------------------------- triggers

def test_music_style_without_style_facts_triggers():
    """Spec §28.3's own case: music present, genres and instruments empty, role music_style."""
    obs = _obs(music=AudioMusicProfile(present=True))
    d = decide_fallback(obs, Role.MUSIC_STYLE)
    assert d.use_fallback and any("genres or instruments" in r for r in d.reasons)


def test_the_same_observation_under_bgm_does_not_trigger():
    """Spec §28.3's other half: signal reuse needs no style description."""
    obs = _obs(music=AudioMusicProfile(present=True))
    assert not decide_fallback(obs, Role.BGM).use_fallback


def test_voice_timbre_with_speech_but_no_profile_triggers():
    obs = _obs(speech=[TimedSpeech(start_s=0.5, end_s=2.0, text="hi", confidence=0.9)],
               voice=AudioVoiceProfile())
    d = decide_fallback(obs, Role.VOICE_TIMBRE)
    assert d.use_fallback and any("voice profile" in r for r in d.reasons)


def test_sfx_without_a_confident_event_triggers():
    obs = _obs(events=[AudioEvent(start_s=1.0, end_s=1.2, label="unknown", confidence=0.3)])
    d = decide_fallback(obs, Role.SFX, event_confidence_threshold=0.55)
    assert d.use_fallback and any("confidence threshold" in r for r in d.reasons)


def test_a_partial_observation_triggers():
    d = decide_fallback(_obs(partial=True), Role.BGM)
    assert d.use_fallback and any("partial" in r for r in d.reasons)


def test_low_mean_confidence_triggers():
    obs = _obs(speech=[TimedSpeech(start_s=0.5, end_s=2.0, text="hi", confidence=0.40)],
               rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.50))
    d = decide_fallback(obs, Role.BGM, confidence_threshold=0.65)
    assert d.use_fallback and any("mean analyser confidence" in r for r in d.reasons)


def test_the_caller_asking_for_detail_triggers():
    d = decide_fallback(_obs(), Role.BGM, caller_note="please give a detailed sound description")
    assert d.use_fallback and any("caller" in r for r in d.reasons)
    assert caller_asked_for_detail("instrumentation details, please")
    assert not caller_asked_for_detail("the client's title track")


def test_a_complex_mixture_triggers():
    obs = _obs(speech=[TimedSpeech(start_s=0.5, end_s=2.0, text="hi")],
               music=AudioMusicProfile(present=True, genres=["electronic"]),
               events=[AudioEvent(start_s=1.0, end_s=1.2, label="impact"),
                       AudioEvent(start_s=2.0, end_s=2.2, label="siren")])
    assert decide_fallback(obs, Role.BGM).use_fallback


# ---------------------------------------------------------------- the silent half

def test_a_clear_asr_result_stays_silent():
    obs = _obs(speech=[TimedSpeech(start_s=0.5, end_s=2.0, text="hi", confidence=0.95)],
               voice=AudioVoiceProfile(speaker_count=1, pitch_class="low", energy="low",
                                       pace="slow"))
    assert not decide_fallback(obs, Role.VOICE_TIMBRE).use_fallback


def test_a_reliable_beat_reference_stays_silent():
    obs = _obs(rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.94,
                                  beat_times_s=[0.47, 0.94, 1.41]))
    assert not decide_fallback(obs, Role.BEAT_REFERENCE).use_fallback


def test_a_plain_bgm_copy_stays_silent():
    obs = _obs(music=AudioMusicProfile(present=True, genres=["electronic"],
                                       instruments=["synth"]),
               rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.94))
    assert not decide_fallback(obs, Role.BGM).use_fallback


def test_sfx_with_a_confident_event_stays_silent():
    obs = _obs(events=[AudioEvent(start_s=1.0, end_s=1.2, label="impact", confidence=0.88)])
    assert not decide_fallback(obs, Role.SFX).use_fallback
