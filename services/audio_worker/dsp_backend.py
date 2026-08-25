"""The DSP tier: exact facts from the signal itself.

ffprobe/ffprobe-grade facts (duration, sample rate, channels) plus numpy analysis of the
decoded waveform (loudness, silence, peaks, onsets, tempo). This is merge-policy Tier 1 on the
compiler side: what it says outranks every model tier, so it is held to a corresponding
standard -- no model call, no narrative, numbers or nothing.

Decoding always goes through ffmpeg to 16 kHz mono s16 PCM, whatever the upload's container:
the analysis math gets one canonical signal and the container codecs are ffmpeg's problem.
Never shell=True -- a filename is data, and the day one contains a space and a semicolon the
shell is the exploit.

librosa is an OPTIONAL enhancement: with it, tempo and beat times come from a real beat
tracker; without it, tempo comes from onset-envelope autocorrelation and beat times stay
empty, reported through `degraded` so the response is marked incomplete rather than silently
thinner.
"""
from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("audio_worker.dsp")

# Analysis runs at 16 kHz mono regardless of the source: speech models want it, and loudness /
# onset math does not care about the difference between 44.1k and 48k content.
ANALYSIS_SR = 16000
FRAME_S, HOP_S = 0.025, 0.010
# Below this short-time RMS a frame is silence. -45 dBFS is quiet enough that room tone on a
# decent recording does not count, loud enough that a genuine gap in a podcast does.
SILENCE_DB = -45.0
MIN_SILENCE_S = 0.30
# Onset picking: energy-flux peaks this many standard deviations above the mean, at least this
# far apart. 50 ms is roughly the perceptual fusion window for separate transients.
ONSET_STD_K = 1.5
MIN_ONSET_GAP_S = 0.05
# Tempo search band. Outside it the autocorrelation peak is as likely to be a multiple or a
# subdivision of the truth as the truth, and a wrong BPM is worse than none.
MIN_BPM, MAX_BPM = 40.0, 240.0


class BackendUnavailable(RuntimeError):
    """This backend cannot run here (missing binary, missing package, no model id).

    A distinct class so the app can answer "this stage is absent" differently from "this stage
    crashed on your file": the first is a property of the deployment, the second of the input.
    """


class AnalysisError(RuntimeError):
    """The input could not be decoded or analysed. The caller's file is the suspect."""


@dataclass
class DSPResult:
    signal: dict[str, Any]
    rhythm: dict[str, Any]
    # What could not be produced and why. Non-empty means the response is marked incomplete:
    # a thinner answer must be a marked answer.
    degraded: list[str] = field(default_factory=list)


def _np():
    try:
        import numpy as np
        return np
    except ImportError as e:
        raise BackendUnavailable(
            "numpy is not installed; the DSP backend needs it (see requirements.txt)") from e


class DSPBackend:
    name = "dsp"

    def __init__(self, settings=None):
        self.settings = settings

    def available(self) -> tuple[bool, str]:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            return False, "ffmpeg/ffprobe not on PATH"
        try:
            import numpy  # noqa: F401
        except ImportError:
            return False, "numpy not installed"
        return True, ""

    # ------------------------------------------------------------------ container facts

    def probe(self, path: str | Path) -> dict[str, Any]:
        """Duration / sample rate / channels of the FILE, via ffprobe. These describe the asset
        as the caller handed it over; the analysis below runs on a 16 kHz mono decode."""
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=sample_rate,channels",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise AnalysisError(f"ffprobe could not read {path}: {out.stderr.strip()[:200]}")
        try:
            info = json.loads(out.stdout)
            duration = float(info["format"]["duration"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise AnalysisError(f"ffprobe returned no duration for {path}") from e
        stream = next((s for s in info.get("streams", []) if s.get("sample_rate")), {})
        return {
            "duration_s": duration,
            "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            "channels": int(stream["channels"]) if stream.get("channels") else None,
        }

    # ------------------------------------------------------------------ decode

    def decode(self, path: str | Path) -> "tuple[Any, int]":
        """-> (mono float32 samples in [-1, 1], ANALYSIS_SR)."""
        np = _np()
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
             "-vn", "-ac", "1", "-ar", str(ANALYSIS_SR), "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=120)
        if out.returncode != 0 or not out.stdout:
            raise AnalysisError(
                f"ffmpeg could not decode audio from {path}: {out.stderr.decode(errors='replace')[:200]}")
        pcm = np.frombuffer(out.stdout, dtype=np.int16)
        if pcm.size == 0:
            raise AnalysisError(f"ffmpeg decoded zero samples from {path} -- is there an audio stream?")
        return pcm.astype(np.float32) / 32768.0, ANALYSIS_SR

    # ------------------------------------------------------------------ measurements

    @staticmethod
    def _frame_rms(samples, sr: int):
        np = _np()
        frame, hop = int(FRAME_S * sr), int(HOP_S * sr)
        n_frames = 1 + max(0, (len(samples) - frame) // hop)
        if n_frames <= 0:
            return np.zeros(0), hop
        idx = np.arange(frame)[None, :] + hop * np.arange(n_frames)[:, None]
        frames = samples[idx]
        return np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12), hop

    @classmethod
    def loudness(cls, samples, sr: int) -> dict[str, Any]:
        np = _np()
        rms, hop = cls._frame_rms(samples, sr)
        eps = 1e-12
        avg_db = float(20 * math.log10(float(np.sqrt(np.mean(samples ** 2))) + eps)) \
            if len(samples) else -120.0
        peak_i = int(np.argmax(np.abs(samples))) if len(samples) else 0
        if rms.size:
            db = 20 * np.log10(rms + eps)
            dynamic = float(np.percentile(db, 95) - np.percentile(db, 10))
        else:
            dynamic = 0.0
        return {"avg_loudness_db": round(avg_db, 2),
                "peak_time_s": round(peak_i / sr, 3),
                "dynamic_range_db": round(dynamic, 2)}

    @classmethod
    def silence_regions(cls, samples, sr: int) -> list[list[float]]:
        np = _np()
        rms, hop = cls._frame_rms(samples, sr)
        if not rms.size:
            return []
        silent = 20 * np.log10(rms + 1e-12) < SILENCE_DB
        regions, start = [], None
        for i, is_silent in enumerate(silent):
            if is_silent and start is None:
                start = i
            elif not is_silent and start is not None:
                regions.append((start, i))
                start = None
        if start is not None:
            regions.append((start, len(silent)))
        out = []
        for a, b in regions:
            t0, t1 = a * hop / sr, b * hop / sr
            if t1 - t0 >= MIN_SILENCE_S:
                out.append([round(t0, 3), round(min(t1, len(samples) / sr), 3)])
        return out

    @classmethod
    def onsets(cls, samples, sr: int) -> list[float]:
        np = _np()
        rms, hop = cls._frame_rms(samples, sr)
        if rms.size < 3:
            return []
        flux = np.diff(rms)
        floor = float(flux.mean() + ONSET_STD_K * flux.std())
        if floor <= 0:
            return []
        min_gap = max(1, int(MIN_ONSET_GAP_S / HOP_S))
        times, last = [], -min_gap
        for i in range(1, len(flux)):
            if flux[i] > floor and flux[i] >= flux[i - 1] and \
                    (i + 1 >= len(flux) or flux[i] >= flux[i + 1]) and i - last >= min_gap:
                times.append(round((i + 1) * hop / sr, 3))
                last = i
        return times

    @classmethod
    def tempo(cls, samples, sr: int) -> tuple[float | None, list[float], list[str]]:
        """(bpm, beat_times, degraded). librosa when it is there; an onset-envelope
        autocorrelation when it is not -- and beats only with the real tracker, because a
        grid placed by hand around sparse onsets is a guess wearing a timestamp."""
        try:
            import librosa  # noqa: PLC0415 - optional heavyweight, imported late on purpose
        except ImportError:
            bpm = cls._tempo_autocorrelation(samples, sr)
            return bpm, [], (["beat tracking needs librosa; tempo is an autocorrelation "
                              "estimate and beat times are unavailable"] if bpm else
                             ["tempo and beats need librosa, which is not installed"])
        try:
            tempo_val, beat_frames = librosa.beat.beat_track(y=samples, sr=sr)
            bpm = float(tempo_val[0] if hasattr(tempo_val, "__len__") else tempo_val)
            beats = [round(float(t), 3) for t in librosa.frames_to_time(beat_frames, sr=sr)]
            return (bpm if MIN_BPM <= bpm <= MAX_BPM else None), beats, []
        except Exception as e:  # noqa: BLE001 - a tracker crash must not kill the DSP tier
            log.warning("librosa beat tracking failed: %s", e)
            return cls._tempo_autocorrelation(samples, sr), [], [
                f"librosa beat tracking failed ({e}); tempo is an autocorrelation estimate"]

    @classmethod
    def _tempo_autocorrelation(cls, samples, sr: int) -> float | None:
        np = _np()
        rms, hop = cls._frame_rms(samples, sr)
        if rms.size < 16:
            return None
        env = np.diff(rms)
        env = env - env.mean()
        if float(np.abs(env).max()) <= 1e-9:
            return None
        ac = np.correlate(env, env, mode="full")[len(env) - 1:]
        lo = max(1, int(round((60.0 / MAX_BPM) / HOP_S)))  # lag, in hops, at the band edges
        hi = min(len(ac) - 1, int(round((60.0 / MIN_BPM) / HOP_S)))
        if hi <= lo:
            return None
        lag = lo + int(np.argmax(ac[lo:hi + 1]))
        bpm = 60.0 / (lag * HOP_S)
        return round(bpm, 1) if MIN_BPM <= bpm <= MAX_BPM else None

    # ------------------------------------------------------------------ entry point

    def analyse(self, path: str | Path) -> DSPResult:
        ok, why = self.available()
        if not ok:
            raise BackendUnavailable(why)
        facts = self.probe(path)
        samples, sr = self.decode(path)
        loud = self.loudness(samples, sr)
        silence = self.silence_regions(samples, sr)
        onset_times = self.onsets(samples, sr)
        bpm, beats, degraded = self.tempo(samples, sr)
        signal = {
            "duration_s": round(facts["duration_s"], 3),
            "sample_rate": facts["sample_rate"],
            "channels": facts["channels"],
            **loud,
            "silence_regions": silence,
        }
        rhythm = {
            "tempo_bpm": bpm,
            # Autocorrelation tempo is an estimate and is marked as such; librosa's tracker
            # earns the higher confidence.
            "confidence": (0.9 if not degraded and bpm is not None else
                           (0.5 if bpm is not None else None)),
            "beat_times_s": beats,
            "downbeat_times_s": [],
            # Onsets loud enough to cut on, capped so the planner gets salient hits rather
            # than every transient in the file.
            "strong_onsets_s": onset_times[:32],
        }
        return DSPResult(signal=signal, rhythm=rhythm, degraded=degraded)
