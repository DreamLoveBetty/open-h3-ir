"""CLAP backend tests: window planning and event merging are pure; the pipeline runs on a
fake scorer. No torch, no weights -- the model call is verified at bring-up, not here."""
from __future__ import annotations

import pytest

from audio_worker.clap_backend import (CLAPBackend, EVENT_FLOOR, plan_windows,
                                       windows_to_events)
from audio_worker.dsp_backend import BackendUnavailable
from audio_worker.settings import WorkerSettings


# ------------------------------------------------------------------ plan_windows

def test_sliding_windows_cover_the_whole_file():
    ws = plan_windows(5.0, window_s=2.0, hop_s=1.0)
    assert ws[0] == (0.0, 2.0)
    assert ws[-1][1] == 5.0, "coverage must reach the end of the file"
    for prev, cur in zip(ws, ws[1:]):
        assert cur[0] <= prev[1], "no gaps in sliding coverage"


def test_a_file_shorter_than_one_window_is_one_window():
    assert plan_windows(0.8) == [(0.0, 0.8)]


def test_onset_windows_are_added_and_aligned_to_the_attack():
    ws = plan_windows(6.0, onsets=[3.37], window_s=2.0)
    assert any(abs(w[0] - 3.32) < 0.01 for w in ws), \
        "an onset at 3.37 must produce a window starting ~50 ms before it"


def test_duplicate_windows_are_removed():
    # an onset at 0.05 produces the same window as the sliding grid's first
    ws = plan_windows(4.0, onsets=[0.05], window_s=2.0, hop_s=1.0)
    assert len(ws) == len(set(ws))


def test_the_cap_coarsens_the_grid_but_keeps_coverage():
    ws = plan_windows(200.0, onsets=[float(i) for i in range(200)], window_s=2.0, hop_s=1.0,
                      max_windows=50)
    assert len(ws) <= 50
    assert ws[0][0] == 0.0 and ws[-1][1] == 200.0, \
        "the cap coarsens the grid; it must never truncate coverage"
    for prev, cur in zip(ws, ws[1:]):
        assert cur[0] <= prev[1], "coarsening preserves overlap, not gaps"


def test_an_empty_file_has_no_windows():
    assert plan_windows(0.0) == []


# ------------------------------------------------------------------ windows_to_events

def test_labels_below_the_floor_are_dropped():
    assert windows_to_events([(0.0, 2.0, [("rain", EVENT_FLOOR - 0.01)])]) == []


def test_adjacent_windows_with_the_same_label_merge_with_max_confidence():
    events = windows_to_events([
        (0.0, 2.0, [("rain", 0.6)]),
        (1.0, 3.0, [("rain", 0.8)]),
    ])
    assert events == [{"start_s": 0.0, "end_s": 3.0, "label": "rain",
                       "confidence": 0.8, "source": "clap"}]


def test_disjoint_labels_in_one_window_both_survive():
    events = windows_to_events([(0.0, 2.0, [("rain", 0.7), ("thunder", 0.5)])])
    assert {e["label"] for e in events} == {"rain", "thunder"}


def test_separated_occurrences_of_one_label_stay_two_events():
    events = windows_to_events([
        (0.0, 2.0, [("door slam", 0.7)]),
        (5.0, 7.0, [("door slam", 0.9)]),
    ])
    assert len(events) == 2
    assert [e["end_s"] for e in events] == [2.0, 7.0]


# ------------------------------------------------------------------ the pipeline, fake model

class _Settings:  # a plain stand-in; the backend reads three attrs and nothing else
    clap_model = "laion/clap-htsat-unfused"
    device = "cpu"
    model_dir = None


def test_located_events_come_out_located():
    """The spec's whole point (§4.6): a sound at 4s must not become a label for the whole
    file. The fake 'model' hears energy, and only the 4s window has any."""
    np = pytest.importorskip("numpy")
    sr = 48000
    samples = np.zeros(6 * sr, dtype=np.float32)
    rng = np.random.default_rng(7)
    samples[4 * sr:5 * sr] = rng.standard_normal(sr).astype(np.float32) * 0.5

    def energy_model(chunk, _sr, labels):
        loud = float(np.sqrt(np.mean(chunk ** 2))) > 0.05
        label = "door slam" if loud else "room tone"
        rest = [(l, 0.0) for l in labels if l != label]
        return [(label, 0.9)] + rest

    backend = CLAPBackend(_Settings(), scorer=energy_model)
    events = backend._classify_samples(samples, onsets=[4.2])
    slams = [e for e in events if e["label"] == "door slam"]
    assert slams, f"the burst at 4s must be detected, got {events}"
    for e in slams:
        assert e["start_s"] >= 3.0 and e["end_s"] <= 6.0, \
            f"the slam must be located near 4s, got {e}"
        assert e["end_s"] - e["start_s"] <= 3.5, "a located event must not span the file"
    tones = [e for e in events if e["label"] == "room tone"]
    assert tones, "the quiet windows must still be classified, as what they are"


def test_a_silver_of_audio_at_the_tail_is_not_classified():
    np = pytest.importorskip("numpy")
    sr = 48000
    samples = np.zeros(int(2.05 * sr), dtype=np.float32)  # a 50 ms sliver past the window
    calls = []

    def counting_model(chunk, _sr, labels):
        calls.append(len(chunk))
        return [("room tone", 0.9)] + [(l, 0.0) for l in labels if l != "room tone"]

    backend = CLAPBackend(_Settings(), scorer=counting_model)
    backend._classify_samples(samples)
    assert all(n >= sr // 10 for n in calls), "sub-100ms slivers must not be scored"


def test_a_backend_without_transformers_reports_unavailable():
    backend = CLAPBackend(_Settings())
    ok, why = backend.available()
    if not ok:  # a box without torch/transformers: the honest answer IS the contract
        assert "transformers" in why or "torch" in why


def test_classify_windows_without_a_model_raises_unavailable(tmp_path, monkeypatch):
    backend = CLAPBackend(_Settings())
    monkeypatch.setattr(backend, "available", lambda: (False, "no transformers here"))
    with pytest.raises(BackendUnavailable, match="no transformers here"):
        backend.classify_windows(tmp_path / "x.wav")
