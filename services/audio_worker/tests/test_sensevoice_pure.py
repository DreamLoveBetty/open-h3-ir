"""The speech tier's pure logic: tag parsing, segment merging, speaker clustering.

The model calls are not tested here (no weights, no GPU); what IS tested is everything the
model's output flows through, because that is where a wrong assumption would live. If FunASR's
tag format drifts, parse_sensevoice_tags is where the compiler finds out.
"""
from __future__ import annotations

import math

import pytest

from audio_worker.sensevoice_backend import (cluster_speakers, merge_close_segments,
                                             parse_sensevoice_tags)


def test_tags_split_from_the_transcript():
    out = parse_sensevoice_tags("<|zh|><|FEARFUL|><|Speech|>别动。")
    assert out == {"text": "别动。", "language": "zh", "emotion": "fearful", "events": []}


def test_event_tags_become_events_and_bgm_is_one():
    out = parse_sensevoice_tags("<|en|><|NEUTRAL|><|BGM|><|Applause|>")
    assert out["text"] == ""
    assert out["events"] == ["bgm", "applause"]
    assert out["emotion"] == "neutral"


def test_unknown_tags_are_dropped_not_leaked():
    """A tag the model invents next month must not reach the IR as dialogue text."""
    out = parse_sensevoice_tags("<|en|><|SOME_NEW_TAG|><|Speech|>hello there")
    assert out["text"] == "hello there"
    assert out["events"] == []


def test_no_tags_is_just_text():
    out = parse_sensevoice_tags("plain transcript")
    assert out == {"text": "plain transcript", "language": "", "emotion": "", "events": []}


def test_merge_close_segments_joins_breaths_not_sentences():
    segs = [[0, 500], [600, 1200], [3000, 4000]]  # 100ms gap joins, 1800ms gap does not
    assert merge_close_segments(segs) == [[0.0, 1200.0], [3000.0, 4000.0]]


def test_merge_close_segments_sorts_and_never_shrinks():
    assert merge_close_segments([[1000, 2000], [900, 1500]]) == [[900.0, 2000.0]]


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def test_clustering_separates_two_voices_in_order_of_first_appearance():
    a = _unit([1.0, 0.0, 0.1])
    b = _unit([0.0, 1.0, 0.1])
    labels = cluster_speakers([a, b, a, b, a], threshold=0.65)
    assert labels == ["SPK_0", "SPK_1", "SPK_0", "SPK_1", "SPK_0"]


def test_clustering_is_not_fooled_by_volume():
    """Cosine, not magnitude: the same voice louder is the same speaker."""
    a = _unit([1.0, 0.2])
    louder_a = [x * 5 for x in a]
    assert cluster_speakers([a, louder_a], threshold=0.65) == ["SPK_0", "SPK_0"]


def test_a_midpoint_voice_joins_the_first_cluster_it_resembles():
    """Greedy-by-design: the labelling rule is documented and deterministic, so a surprising
    assignment is a debuggable fact rather than k-means' mood."""
    a = _unit([1.0, 0.0])
    b = _unit([0.0, 1.0])
    mid = _unit([1.0, 0.6])     # cos(mid, a) ≈ 0.86 > cos(mid, b) ≈ 0.51
    labels = cluster_speakers([a, b, mid], threshold=0.65)
    assert labels == ["SPK_0", "SPK_1", "SPK_0"]


def test_no_embeddings_no_labels():
    assert cluster_speakers([], 0.65) == []


# ------------------------------------------------------------------ the model identity

def test_the_model_id_names_every_model_in_the_chain():
    """The compiler keys its observation cache on this id. Swapping ONLY the VAD or the
    speaker model changes what this backend produces, so an id that named just the ASR model
    would let a cached observation survive the swap that invalidated it."""
    from audio_worker.sensevoice_backend import SenseVoiceBackend
    from audio_worker.settings import WorkerSettings

    s = WorkerSettings(sensevoice_model="iic/SenseVoiceSmall",
                       vad_model="iic/fsmn-vad", speaker_model="iic/campplus")
    mid = SenseVoiceBackend(s).model_id
    assert "iic/SenseVoiceSmall" in mid and "iic/fsmn-vad" in mid and "iic/campplus" in mid

    bare = WorkerSettings(sensevoice_model="iic/SenseVoiceSmall", vad_model="",
                          speaker_model="")
    assert SenseVoiceBackend(bare).model_id == "iic/SenseVoiceSmall"
