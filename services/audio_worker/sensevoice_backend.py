"""The speech tier: FSMN-VAD segmentation, SenseVoiceSmall ASR, CAM++ speaker clustering.

Three model jobs, one file, because they share one pipeline: the VAD decides where speech IS
(so SenseVoice never burns compute on silence and the segments it returns are real), SenseVoice
transcribes each segment and reports its language and coarse emotion as inline tags, and CAM++
embeds each segment so the compiler can say "the same voice" without ever claiming to know
whose voice it is. A `SPK_0` is a cluster label, never an identity.

Everything pure is split from everything that touches torch:

  * parse_sensevoice_tags / cluster_speakers / merge_close_segments are ordinary functions and
    are unit-tested without a GPU or a model file.
  * The model plumbing loads lazily and reports unavailability with a reason, so the worker
    answers honestly (and marks its responses incomplete) on a box with no FunASR install.

Written against the FunASR AutoModel interface (`iic/SenseVoiceSmall`,
`iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`, `iic/speech_campplus_sv_zh-cn_16k-common` --
the old `..._zh_en_16k` id 404s on ModelScope since its rename). The pure
helpers are tested; the model calls themselves get their live verification at bring-up on real
weights, which is a deployment step, not a unit test.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dsp_backend import ANALYSIS_SR, BackendUnavailable, _np

log = logging.getLogger("audio_worker.sensevoice")

_TAG = re.compile(r"<\|([^|]+)\|>")

_LANGUAGES = {"zh": "zh", "en": "en", "yue": "yue", "ja": "ja", "ko": "ko"}
_EMOTIONS = {"HAPPY": "happy", "SAD": "sad", "ANGRY": "angry", "NEUTRAL": "neutral",
             "FEARFUL": "fearful", "DISGUSTED": "disgusted", "SURPRISED": "surprised"}
# SenseVoice's audio-event vocabulary, lower-cased for the wire. "Speech" itself is not an
# event -- it is what the segment IS.
_EVENTS = {"APPLAUSE": "applause", "BGM": "bgm", "LAUGHTER": "laughter", "CRY": "cry",
           "SNEEZE": "sneeze", "BREATH": "breath", "COUGH": "cough", "KEYBOARD": "keyboard",
           "MOUSE": "mouse", "DOOR": "door", "ALARM": "alarm", "PHONE": "phone",
           "CAR": "car", "ENGINE": "engine", "NOISE": "noise"}

# VAD fragments closer than this are one breath, not two utterances: joining them spares
# SenseVoice a per-fragment call and the speaker clustering a per-fragment embedding.
MERGE_GAP_MS = 300


def _segment_wav(samples, sr: int, s_ms: float, e_ms: float) -> str:
    """A VAD window as its own 16 kHz mono wav, so the ASR and speaker models hear exactly
    the segment and nothing around it. Caller unlinks the path."""
    import tempfile
    import wave

    np = _np()
    lo = max(0, int(s_ms * sr / 1000.0))
    hi = min(len(samples), int(math.ceil(e_ms * sr / 1000.0)))
    pcm = (np.clip(samples[lo:hi], -1.0, 1.0) * 32767.0).astype(np.int16)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        with wave.open(f.name, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
    finally:
        f.close()
    return f.name


def parse_sensevoice_tags(text: str) -> dict[str, Any]:
    """Split SenseVoice's inline tags from the transcript it prefixes them to.

    `<|zh|><|FEARFUL|><|Speech|>Don't move.` -> text "Don't move.", language "zh",
    emotion "fearful", events []. A tag we do not know is dropped rather than leaked into the
    transcript: the compiler's validator reads the text, and `<|HAPPY|>` is not dialogue.
    """
    language, emotion, events = "", "", []
    for tag in _TAG.findall(text or ""):
        if tag.lower() in _LANGUAGES:
            language = _LANGUAGES[tag.lower()]
        elif tag.upper() in _EMOTIONS:
            emotion = _EMOTIONS[tag.upper()]
        elif tag.upper() in _EVENTS:
            events.append(_EVENTS[tag.upper()])
    clean = _TAG.sub("", text or "").strip()
    return {"text": clean, "language": language, "emotion": emotion, "events": events}


def merge_close_segments(segments: list[list[float]], gap_ms: int = MERGE_GAP_MS
                         ) -> list[list[float]]:
    """Join VAD fragments separated by less than a breath. Input is [[start_ms, end_ms], ...]
    in file order."""
    out: list[list[float]] = []
    for seg in sorted(segments):
        if out and seg[0] - out[-1][1] < gap_ms:
            out[-1][1] = max(out[-1][1], seg[1])
        else:
            out.append([float(seg[0]), float(seg[1])])
    return out


def cluster_speakers(embeddings: list[list[float]], threshold: float) -> list[str]:
    """Greedy first-seen clustering on cosine similarity.

    Deliberately the simplest thing that is honest: no k-means k to guess, no linkage
    hyperparameters, and labels assigned in order of first appearance so `SPK_0` is the first
    voice heard. A segment joins the FIRST cluster it resembles; clusters are never merged
    after the fact, which keeps the labelling order-independent in the only direction that
    matters (earlier segments cannot change their minds because a later one arrived).
    """
    if not embeddings:
        return []

    def _unit(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    reps: list[list[float]] = []
    labels: list[str] = []
    for raw in embeddings:
        v = _unit([float(x) for x in raw])
        placed = None
        for i, rep in enumerate(reps):
            if sum(a * b for a, b in zip(v, rep)) >= threshold:
                placed = i
                break
        if placed is None:
            reps.append(v)
            placed = len(reps) - 1
        labels.append(f"SPK_{placed}")
    return labels


@dataclass
class SpeechResult:
    speech: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)   # coarse, from ASR tags
    voice: dict[str, Any] = field(default_factory=dict)
    music_present: bool = False
    degraded: list[str] = field(default_factory=list)


class SenseVoiceBackend:
    name = "speech"

    def __init__(self, settings):
        self.settings = settings
        self._asr = None
        self._vad = None
        self._spk = None

    @property
    def model_id(self) -> str:
        """The identity the compiler's observation cache keys on. It must name ALL THREE
        models: swapping only the VAD or the speaker model changes the observations this
        backend produces, and an id of bare "speech" would let a cached observation survive
        the swap that invalidated it."""
        s = self.settings
        return "+".join(p for p in (s.sensevoice_model, s.vad_model, s.speaker_model) if p)

    def available(self) -> tuple[bool, str]:
        try:
            import funasr  # noqa: F401
        except ImportError:
            return False, "funasr is not installed (pip install funasr torch)"
        if not self.settings.sensevoice_model:
            return False, "AUDIO_WORKER_SENSEVOICE_MODEL is empty"
        return True, ""

    # ------------------------------------------------------------------ lazy models

    def _load(self) -> None:
        if self._asr is not None:
            return
        from funasr import AutoModel  # noqa: PLC0415 - heavyweight, loaded on first use only
        kw = {"device": self.settings.device, "disable_update": True}
        if self.settings.model_dir:
            kw["model_path"] = str(self.settings.model_dir)
        self._asr = AutoModel(model=self.settings.sensevoice_model, **kw)
        if self.settings.vad_model:
            self._vad = AutoModel(model=self.settings.vad_model, **kw)
        if self.settings.speaker_model:
            self._spk = AutoModel(model=self.settings.speaker_model, **kw)

    # ------------------------------------------------------------------ pipeline

    def _segments(self, wav16k: str | Path) -> list[list[float]]:
        """Speech regions in ms. Without a VAD model the whole file is one segment -- correct
        for the short references H3 takes, and marked degraded by the caller via `available()`.
        """
        if self._vad is None:
            from .dsp_backend import DSPBackend  # local import: only needed for the fallback
            dur = DSPBackend().probe(wav16k)["duration_s"]
            return [[0.0, dur * 1000.0]]
        # FunASR >= 1.x exposes generate(); the .infer this file was drafted against never
        # existed on AutoModel -- found at first bring-up on real weights.
        res = self._vad.generate(input=str(wav16k))
        value = res[0].get("value") or res[0].get("segments") or []
        return merge_close_segments([[float(s), float(e)] for s, e in value])

    def analyse(self, wav16k: str | Path, *, diarization: bool = True) -> SpeechResult:
        ok, why = self.available()
        if not ok:
            raise BackendUnavailable(why)
        self._load()
        out = SpeechResult()
        segments = self._segments(wav16k)
        # Decoded once: SenseVoice's generate() has no vad_segments kwarg (another bring-up
        # find), so each VAD window is cut to its own temp wav and the models hear exactly the
        # segment. Seconds-long references make the slice cost negligible.
        from .dsp_backend import DSPBackend  # local import: torch-free, but only needed here
        samples, sr = DSPBackend(self.settings).decode(wav16k)
        embeddings: list[list[float]] = []
        embeddable: list[int] = []
        for i, (s_ms, e_ms) in enumerate(segments):
            seg_path = _segment_wav(samples, sr, s_ms, e_ms)
            try:
                res = self._asr.generate(input=seg_path, cache={}, language="auto",
                                         use_itn=True,  # readable numbers/punctuation
                                         )
                if not res:
                    continue
                parsed = parse_sensevoice_tags(res[0].get("text", ""))
                if not parsed["text"] and not parsed["events"]:
                    continue
                entry = {"start_s": round(s_ms / 1000.0, 3), "end_s": round(e_ms / 1000.0, 3),
                         "text": parsed["text"], "language": parsed["language"],
                         "speaker_id": "", "emotion": parsed["emotion"], "confidence": None}
                out.speech.append(entry)
                for label in parsed["events"]:
                    out.events.append({"start_s": entry["start_s"], "end_s": entry["end_s"],
                                       "label": label, "confidence": None, "source": "sensevoice"})
                    if label == "bgm":
                        out.music_present = True
                if diarization and self._spk is not None and parsed["text"]:
                    embeddings.append(self._embed(seg_path))
                    embeddable.append(len(out.speech) - 1)
            finally:
                Path(seg_path).unlink(missing_ok=True)
        if diarization and embeddings:
            labels = cluster_speakers(embeddings, self.settings.speaker_threshold)
            for idx, label in zip(embeddable, labels):
                out.speech[idx]["speaker_id"] = label
            out.voice["speaker_count"] = len(set(labels))
        elif out.speech:
            out.voice["speaker_count"] = 0  # not measured, and 0 says exactly that
        emotions = sorted({s["emotion"] for s in out.speech if s["emotion"]})
        if emotions:
            out.voice["emotions"] = emotions
        if not diarization and self._spk is None and self.settings.speaker_model:
            out.degraded.append("speaker model unavailable; speaker_count is not measured")
        return out

    def _embed(self, seg_path: str) -> list[float]:
        res = self._spk.generate(input=seg_path)
        # ndarray truthiness is ambiguous, so no `or` chaining here.
        emb = res[0].get("spk_embedding")
        if emb is None:
            emb = res[0].get("embedding")
        if emb is None:
            raise BackendUnavailable("speaker model returned no embedding")
        np = _np()
        # CAM++ returns shape (1, 192): flatten or the floats never come out.
        return [float(x) for x in np.asarray(emb, dtype=np.float32).reshape(-1)]
