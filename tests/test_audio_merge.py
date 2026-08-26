"""The merge policy and the §11 protocol parser (spec §11/§12, §28.4).

The merge test that matters most is the negative one: the fallback cannot move a deterministic
field, by protocol (the parser rejects the key) and by policy (the merge fills only empty
slots). Spec §28.4's tempo conflict is pinned both ways.
"""
from __future__ import annotations

import re

import pytest

from h3ir.audio.fallback import (FALLBACK_USER_PROMPT, PROTOCOL_KEYS,
                                 FallbackPayloadError, parse_fallback_payload)
from h3ir.audio.merge import deterministic_overwrite_attempt, merge_fallback
from h3ir.audio.models import (AudioMusicProfile, AudioObservation, AudioRhythm,
                               AudioSignalFacts, TimedSpeech)


def _obs(**kw) -> AudioObservation:
    base = dict(sha256="f" * 64, signal=AudioSignalFacts(duration_s=6.0))
    base.update(kw)
    return AudioObservation(**base)


# ---------------------------------------------------------------- the parser

def test_a_protocol_payload_parses():
    payload = parse_fallback_payload(
        '{"semantic_summary": "a dense club mix", "music_style": ["techno"], '
        '"instrumentation": ["drum machine"], "soundscape": ["crowd murmur"], '
        '"event_descriptions": [{"approx_start_s": 4.2, "approx_end_s": null, '
        '"description": "a glass shatters"}], "confidence": 0.7}')
    assert payload["music_style"] == ["techno"]
    assert payload["event_descriptions"][0]["approx_start_s"] == 4.2
    assert payload["confidence"] == 0.7


def test_prose_around_the_json_is_accepted_but_prose_instead_is_not():
    assert parse_fallback_payload('Sure! {"semantic_summary": "x"}')["semantic_summary"] == "x"
    with pytest.raises(FallbackPayloadError):
        parse_fallback_payload("I cannot hear this audio.")


def test_a_key_outside_the_protocol_rejects_the_whole_payload():
    with pytest.raises(FallbackPayloadError) as err:
        parse_fallback_payload('{"semantic_summary": "x", "tempo_bpm": 140}')
    assert err.value.extra_keys == ("tempo_bpm",)
    # ...and the merge stage names it A26, because tempo is a deterministic field.
    finding = deterministic_overwrite_attempt(err.value.extra_keys)
    assert finding is not None and finding.rule == "A26-fallback-overwrote-timing"


def test_an_extra_but_harmless_key_is_rejected_without_a26():
    with pytest.raises(FallbackPayloadError) as err:
        parse_fallback_payload('{"semantic_summary": "x", "vibe": "nice"}')
    assert deterministic_overwrite_attempt(err.value.extra_keys) is None


def test_a_confidence_outside_unit_range_is_rejected():
    with pytest.raises(FallbackPayloadError):
        parse_fallback_payload('{"confidence": 1.7}')


def test_the_user_prompt_skeleton_names_exactly_the_protocol_keys():
    # FALLBACK_USER_PROMPT hands the model the §11 key skeleton verbatim and the parser
    # enforces PROTOCOL_KEYS whole-payload; if the two drift apart, every real fallback
    # answer is rejected as off-protocol and the supplement silently never lands. Top-level
    # keys only: the nested approx_* keys of event_descriptions are not protocol keys.
    skeleton_keys = set(re.findall(r'^  "(\w+)":', FALLBACK_USER_PROMPT, re.M))
    assert skeleton_keys == PROTOCOL_KEYS


# ---------------------------------------------------------------- the merge

def test_the_fallback_cannot_move_a_deterministic_tempo():
    """Spec §28.4: DSP says 128.1 @ 0.94; the supplement must leave it exactly there."""
    obs = _obs(rhythm=AudioRhythm(tempo_bpm=128.1, confidence=0.94,
                                  beat_times_s=[0.47, 0.94]))
    payload = parse_fallback_payload('{"semantic_summary": "driving techno at 140 BPM", '
                                     '"confidence": 0.8}')
    merged, _ = merge_fallback(obs, payload)
    assert merged.rhythm.tempo_bpm == 128.1
    assert merged.rhythm.beat_times_s == [0.47, 0.94]


def test_empty_slots_are_filled_and_full_ones_are_kept():
    obs = _obs(music=AudioMusicProfile(present=True, genres=["techno"], instruments=[]))
    payload = parse_fallback_payload('{"music_style": ["house"], "instrumentation": '
                                     '["drum machine", "acid bass"], "confidence": 0.7}')
    merged, _ = merge_fallback(obs, payload)
    assert merged.music.genres == ["techno"], "tier 2 outranks tier 3"
    assert merged.music.instruments == ["drum machine", "acid bass"]
    assert merged.fallback_used


def test_fallback_event_descriptions_never_enter_the_event_list():
    """Approximate descriptions are semantic facts; `events` is tier-2 located detections, and
    the timeline stage maps that list onto shots as if it were measured."""
    obs = _obs()
    payload = parse_fallback_payload('{"event_descriptions": [{"approx_start_s": 4.2, '
                                     '"approx_end_s": null, "description": "a glass shatters"}]}')
    merged, _ = merge_fallback(obs, payload)
    assert merged.events == []
    assert any("glass shatters" in f and "4.2" in f for f in merged.semantic_facts)


def test_a_payload_that_fills_nothing_marks_no_fallback():
    obs = _obs(semantic_summary="already described")
    payload = parse_fallback_payload('{"semantic_summary": "ignored, slot full"}')
    merged, _ = merge_fallback(obs, payload)
    assert not merged.fallback_used
    assert merged.semantic_summary == "already described"


def test_the_merge_never_mutates_the_cached_observation():
    """The observation may be the cache's own object; merging in place would serve a
    request-specific supplement as a byte-derived fact to the NEXT request."""
    obs = _obs(music=AudioMusicProfile(present=True))
    payload = parse_fallback_payload('{"music_style": ["house"]}')
    merged, _ = merge_fallback(obs, payload)
    assert obs.music.genres == [] and merged.music.genres == ["house"]
    assert not obs.fallback_used and merged.fallback_used
