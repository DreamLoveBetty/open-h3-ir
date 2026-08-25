"""CLAP event / texture semantics: zero-shot labels over time, never one label per file.

Spec §4.6: environment sounds, SFX classes, music/non-music, coarse instruments and texture,
classified over sliding windows PLUS onset-driven windows, each with a confidence. The
whole-file trap is real for CLAP: a door slam at 4.7 s in an otherwise quiet file disappears
into a single embedding of the whole clip, and that located fact is exactly what the SFX role
exists to carry.

Same split as sensevoice_backend.py, for the same reason:

  * plan_windows / windows_to_events are ordinary functions, unit-tested without torch.
  * The model plumbing (laion/clap-htsat-unfused via transformers) loads lazily and reports
    unavailability with a reason; the app turns that into `incomplete: true` on the wire.
  * `_classify_samples` takes a scorer seam so the pipeline -- windowing, slicing, merging --
    is testable with a fake model. The real model call gets its live verification at
    bring-up on real weights, which is a deployment step, not a unit test.

CLAP wants 48 kHz input (HTSAT was trained on it); the DSP tier decodes at 16 kHz for speech,
so this backend decodes its own stream. Same argv discipline as dsp_backend: never a shell.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .dsp_backend import BackendUnavailable

log = logging.getLogger("audio_worker.clap")

CLAP_SR = 48000
WINDOW_S, HOP_S = 2.0, 1.0
# An onset window starts just before the transient so the attack is inside the frame; 50 ms
# is below perceptual fusion and costs the classifier nothing.
ONSET_LOOKBACK_S = 0.05
# Compute bound: sliding windows of a 10-minute cap file plus every onset would be thousands
# of forward passes. Sliding coverage is always kept; onset windows fill what remains.
MAX_WINDOWS = 96
# Below this softmax share a label is noise on the wire. The compiler's router applies its
# own, higher threshold to what survives; this floor only keeps the response honest-sized.
EVENT_FLOOR = 0.25
# Same label in windows this far apart is one event, not two.
MERGE_GAP_S = 0.25

# Zero-shot candidate texts. Plain noun phrases: CLAP's text tower was trained on captions,
# and the label string doubles as the event label on the wire, so it must read as one.
CLAP_LABELS: tuple[str, ...] = (
    # environment
    "rain", "wind", "ocean waves", "thunder", "birdsong", "city traffic", "crowd chatter",
    "room tone",
    # sfx
    "door slam", "footsteps", "gunshot", "explosion", "glass breaking", "car engine",
    "alarm siren", "telephone ring", "keyboard typing", "applause", "laughter",
    "dog barking", "metallic impact",
    # music / instruments
    "background music", "drums", "piano", "guitar", "strings", "synthesizer", "bass guitar",
)


def plan_windows(duration_s: float, onsets: list[float] | None = None,
                 *, window_s: float = WINDOW_S, hop_s: float = HOP_S,
                 max_windows: int = MAX_WINDOWS) -> list[tuple[float, float]]:
    """Sliding coverage plus onset-driven windows, deduplicated, capped.

    Sliding windows tile the file end to end (a shorter-than-window file is one window).
    Onset windows are added on top because a transient can straddle a hop boundary and be
    half-energy in two sliding windows; one frame aligned to the attack classifies it whole.
    Sliding windows win the cap: coverage is the contract, onset windows are refinement.
    When sliding alone would exceed the cap the GRID coarsens proportionally -- window and
    hop scale together, keeping 50% overlap and end-to-end coverage. A coarse grid over the
    whole file beats a fine grid over its first minute: a located answer about the wrong
    seconds is worse than a blurrier answer about all of them.
    """
    if duration_s <= 0:
        return []
    if duration_s / hop_s > max_windows:
        hop_s = duration_s / max_windows
        window_s = 2 * hop_s  # the default grid's 50% overlap, preserved at any scale
    windows: list[tuple[float, float]] = []
    t = 0.0
    while t < duration_s:
        windows.append((t, min(t + window_s, duration_s)))
        t += hop_s
    for onset in sorted(onsets or []):
        if len(windows) >= max_windows:
            break
        if not 0.0 <= onset <= duration_s:
            continue
        start = max(0.0, onset - ONSET_LOOKBACK_S)
        windows.append((start, min(start + window_s, duration_s)))
    # Dedup after rounding to milliseconds; two onsets 60 ms apart are one window.
    seen: set[tuple[int, int]] = set()
    out: list[tuple[float, float]] = []
    for start, end in sorted(windows):
        key = (round(start * 1000), round(end * 1000))
        if key not in seen:
            seen.add(key)
            out.append((round(start, 3), round(end, 3)))
    return out[:max_windows]


def windows_to_events(scored: list[tuple[float, float, list[tuple[str, float]]]],
                      *, min_confidence: float = EVENT_FLOOR) -> list[dict]:
    """Per-window (label, probability) lists -> located, merged event dicts.

    A window contributes every label above the floor. Adjacent or overlapping windows that
    agree on a label merge into one event whose confidence is the MAX, not the mean: the
    number answers "how confident was the model at its most confident", and averaging would
    dilute a sharp detection with the windows where the sound was decaying.
    """
    hits: list[tuple[float, float, str, float]] = []
    for start, end, labels in scored:
        for label, prob in labels:
            if prob >= min_confidence:
                hits.append((start, end, label, float(prob)))
    # Sort by label first so merging only ever looks at the previous event of the SAME label.
    hits.sort(key=lambda h: (h[2], h[0]))
    merged: list[tuple[float, float, str, float]] = []
    for start, end, label, prob in hits:
        if merged and merged[-1][2] == label and start <= merged[-1][1] + MERGE_GAP_S:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), label, max(prev[3], prob))
        else:
            merged.append((start, end, label, prob))
    merged.sort(key=lambda h: h[0])
    return [{"start_s": round(s, 3), "end_s": round(e, 3), "label": label,
             "confidence": round(p, 3), "source": "clap"} for s, e, label, p in merged]


class CLAPBackend:
    name = "clap"

    def __init__(self, settings, scorer=None):
        self.settings = settings
        # Test seam: scorer(chunk_samples, sr, labels) -> [(label, probability), ...].
        # Injecting one skips the model entirely, which is what lets the windowing pipeline
        # be tested on a laptop with no weights.
        self._scorer = scorer
        self._model = None
        self._processor = None

    @property
    def model_id(self) -> str:
        return getattr(self.settings, "clap_model", "") or ""

    def available(self) -> tuple[bool, str]:
        if not self.model_id and self._scorer is None:
            return False, "AUDIO_WORKER_CLAP_MODEL is empty"
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False, "transformers/torch not installed (pip install transformers torch)"
        return True, ""

    # ------------------------------------------------------------------ lazy model

    def _load(self) -> None:
        if self._model is not None or self._scorer is not None:
            return
        from transformers import ClapModel, ClapProcessor  # noqa: PLC0415 - heavyweight, first use only
        kw = {}
        if getattr(self.settings, "model_dir", None):
            kw["cache_folder"] = str(self.settings.model_dir)
        device = getattr(self.settings, "device", "cpu")
        self._processor = ClapProcessor.from_pretrained(self.model_id, **kw)
        self._model = ClapModel.from_pretrained(self.model_id, **kw).to(device)
        self._model.eval()

    def _score_chunk(self, chunk, sr: int, labels: list[str]) -> list[tuple[str, float]]:
        """Softmax over audio-text cosine similarities, the standard CLAP zero-shot read."""
        import torch  # noqa: PLC0415
        device = next(self._model.parameters()).device
        inputs = self._processor(text=list(labels), audios=[chunk], sampling_rate=sr,
                                 return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            out = self._model(**inputs)
        # logits_per_audio: (1, n_labels) cosine similarities scaled by the learned logit scale
        probs = out.logits_per_audio[0].softmax(dim=-1)
        return [(label, float(p)) for label, p in zip(labels, probs)]

    # ------------------------------------------------------------------ pipeline

    def _decode(self, path: str | Path):
        """-> mono float32 samples at CLAP_SR. CLAP was trained at 48 kHz; feeding it the
        speech tier's 16 kHz decode would shift every spectral feature it knows."""
        import numpy as np  # noqa: PLC0415
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
             "-vn", "-ac", "1", "-ar", str(CLAP_SR), "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=120)
        if out.returncode != 0 or not out.stdout:
            raise BackendUnavailable(
                f"ffmpeg could not decode audio from {path} for CLAP: "
                f"{out.stderr.decode(errors='replace')[:200]}")
        pcm = np.frombuffer(out.stdout, dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0

    def _classify_samples(self, samples, onsets: list[float] | None = None) -> list[dict]:
        """The pipeline proper, separated from decoding so tests can feed it arrays."""
        duration_s = len(samples) / CLAP_SR
        windows = plan_windows(duration_s, onsets)
        scorer = self._scorer or self._score_chunk
        scored = []
        for start, end in windows:
            chunk = samples[int(start * CLAP_SR):int(end * CLAP_SR)]
            if len(chunk) < CLAP_SR // 10:
                continue  # a sliver under 100 ms carries no classifiable spectrum
            scored.append((start, end, scorer(chunk, CLAP_SR, list(CLAP_LABELS))))
        return windows_to_events(scored)

    def classify_windows(self, wav16k: str | Path, *, onsets: list[float] | None = None
                         ) -> list[dict]:
        """The app's entry point (the argument name is the app's; any container decodes)."""
        if self._scorer is None:
            ok, why = self.available()
            if not ok:
                raise BackendUnavailable(why)
            self._load()
        return self._classify_samples(self._decode(wav16k), onsets)
