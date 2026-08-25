"""The DSP tier against real synthesised audio through real ffmpeg.

The fixtures are built, not shipped: a WAV with a known click pattern (a tempo the test
controls), a known silence gap, and a known loud pop -- so every assertion compares the
measurement against the number the fixture was constructed to have. No model, no GPU; numpy
and ffmpeg only.
"""
from __future__ import annotations

import math
import shutil
import struct
import wave

import pytest

np = pytest.importorskip("numpy", reason="the DSP backend needs numpy")
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="the DSP backend decodes through ffmpeg")

from audio_worker.dsp_backend import (ANALYSIS_SR, AnalysisError, DSPBackend,
                                      MIN_SILENCE_S)


def _write_wav(path, samples, sr=16000):
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


@pytest.fixture
def click_track(tmp_path):
    """3 s of 120 BPM clicks: a 10 ms burst every 0.5 s from 0.25 s on, a loud pop at 2.0 s,
    and a 0.5 s silence from 1.05 s. Every number asserted below comes from this recipe. The
    silence window is placed BETWEEN clicks on purpose: an earlier draft of this fixture ran
    it over the 1.5 s click and then asserted the click was found -- a fixture that cannot
    discriminate is a comment, not a test."""
    sr = 16000
    t = np.arange(3 * sr) / sr
    samples = np.zeros(3 * sr, dtype=np.float32)
    samples += 0.05 * np.sin(2 * np.pi * 220 * t).astype(np.float32)  # quiet bed, off-silence
    for beat in (0.25, 0.75, 1.75, 2.25, 2.75):  # 0.5 s spacing == 120 BPM
        i = int(beat * sr)
        burst = 0.4 * np.sin(2 * np.pi * 880 * np.arange(int(0.01 * sr)) / sr)
        samples[i:i + len(burst)] += burst.astype(np.float32)
    samples[int(1.05 * sr):int(1.55 * sr)] = 0.0  # the gap, containing no click
    samples[int(2.0 * sr)] = 1.0                  # the pop
    p = tmp_path / "clicks.wav"
    _write_wav(p, samples, sr)
    return p


def test_probe_and_decode_agree_on_duration(click_track):
    dsp = DSPBackend()
    facts = dsp.probe(click_track)
    assert facts["duration_s"] == pytest.approx(3.0, abs=0.05)
    assert facts["sample_rate"] == 16000 and facts["channels"] == 1
    samples, sr = dsp.decode(click_track)
    assert sr == ANALYSIS_SR
    assert len(samples) / sr == pytest.approx(3.0, abs=0.05)


def test_loudness_peak_lands_on_the_pop(click_track):
    dsp = DSPBackend()
    samples, sr = dsp.decode(click_track)
    loud = dsp.loudness(samples, sr)
    assert loud["peak_time_s"] == pytest.approx(2.0, abs=0.02)
    assert loud["avg_loudness_db"] < 0
    assert loud["dynamic_range_db"] > 6, "a bed plus clicks must measure as dynamic"


def test_the_constructed_silence_is_found(click_track):
    dsp = DSPBackend()
    samples, sr = dsp.decode(click_track)
    regions = dsp.silence_regions(samples, sr)
    assert regions, "a 0.5 s dead window was constructed; it must be found"
    start, end = regions[0]
    assert start == pytest.approx(1.05, abs=0.05)
    assert MIN_SILENCE_S <= end - start <= 0.6


def test_onsets_land_on_the_clicks(click_track):
    dsp = DSPBackend()
    samples, sr = dsp.decode(click_track)
    times = dsp.onsets(samples, sr)
    for beat in (0.25, 0.75, 1.75, 2.25, 2.75):
        assert any(abs(t - beat) < 0.05 for t in times), f"no onset near {beat}s: {times}"
    assert not any(1.10 < t < 1.50 for t in times), "the silent gap must produce no onsets"


def test_tempo_reads_the_constructed_120bpm(click_track):
    dsp = DSPBackend()
    samples, sr = dsp.decode(click_track)
    bpm, beats, degraded = dsp.tempo(samples, sr)
    assert bpm is not None
    # The autocorrelation bandpass quantises: 120 BPM is a lag of exactly 50 hops at 10 ms,
    # and either implementation must land within a few BPM of the constructed truth.
    assert bpm == pytest.approx(120.0, abs=4)
    if degraded:
        assert beats == [], "the fallback estimates tempo but must not invent beat times"


def test_analyse_assembles_signal_and_rhythm(click_track):
    result = DSPBackend().analyse(click_track)
    assert result.signal["duration_s"] == pytest.approx(3.0, abs=0.05)
    assert result.rhythm["tempo_bpm"] == pytest.approx(120.0, abs=4)
    assert result.rhythm["strong_onsets_s"], "the clicks are the strong onsets"


def test_an_empty_decode_is_an_error_not_an_empty_answer(tmp_path):
    p = tmp_path / "silent-but-broken.wav"
    _write_wav(p, np.zeros(16000, dtype=np.float32))
    # A zero-length FILE is different from a silent one: truncate mid-header.
    p.write_bytes(p.read_bytes()[:20])
    with pytest.raises(AnalysisError):
        DSPBackend().analyse(p)
