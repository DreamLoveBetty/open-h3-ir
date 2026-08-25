"""The structured facts an audio analyser can stand behind.

The design rule this file exists to serve: an Observation answers "what is objectively in the
audio", never "what the caller wants to do with it". The same music file can be attached as
`bgm`, `music_style` or `beat_reference`; the Observation is identical in all three, and the
differences are produced later by the role-aware projector. That separation is what makes the
Observation content-addressable (cacheable on the bytes alone) while the projection stays
request-specific (never cached).

Nothing here is free prose. The narrative layer (`semantic_summary`, `semantic_facts`) exists
for the Omni fallback to supplement, and it may not restate the deterministic fields: the merge
policy ranks ffprobe/DSP facts above ASR/speaker/CLAP facts above fallback semantics, and a
fallback that contradicts a beat timestamp is a validator error (A26), not a disagreement.

This module deliberately imports nothing from the rest of the package. `h3ir.models.AssetCard`
imports FROM here (it carries an optional observation), so an import in the other direction
would be a cycle.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

# Bumping is not optional when the Observation contract changes, for the reason ANALYZER_VERSION
# exists in analyse.py: the cache is keyed on the bytes AND on the logic that transformed them,
# and a cached observation written against an older contract must miss rather than silently
# answer a question its fields no longer mean. `audio-1` is the first contract: speech, events,
# voice, music, rhythm, signal, plus the fallback's semantic supplement.
AUDIO_ANALYZER_VERSION = "audio-1"


@dataclass
class TimedSpeech:
    """One recognised speech segment. Timestamps are seconds from the start of the asset."""

    start_s: float
    end_s: float
    text: str
    language: str = ""
    # A diarization label ("SPK_0"), NOT a human identity. CAM++ clusters voices; it does not
    # know who anyone is, and the IR must never claim it does.
    speaker_id: str = ""
    emotion: str = ""
    confidence: float | None = None


@dataclass
class AudioEvent:
    """One located sound event, e.g. a CLAP detection window."""

    start_s: float
    end_s: float
    label: str
    confidence: float | None = None
    # Which analyser asserted it ("clap", "sensevoice", "omni-fallback"). Provenance is part of
    # the fact: the merge policy and validator rule A25 need to know where a claim came from.
    source: str = ""


@dataclass
class AudioVoiceProfile:
    speaker_count: int = 0
    pitch_class: str = ""
    energy: str = ""
    pace: str = ""
    delivery: str = ""
    emotions: list[str] = field(default_factory=list)


@dataclass
class AudioMusicProfile:
    present: bool = False
    genres: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    tempo_bpm: float | None = None
    rhythmic_feel: str = ""
    tonal_character: str = ""


@dataclass
class AudioRhythm:
    tempo_bpm: float | None = None
    confidence: float | None = None
    beat_times_s: list[float] = field(default_factory=list)
    downbeat_times_s: list[float] = field(default_factory=list)
    strong_onsets_s: list[float] = field(default_factory=list)


@dataclass
class AudioSignalFacts:
    """The ffprobe/DSP tier: exact, and outranking every model tier in a conflict."""

    duration_s: float = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    avg_loudness_db: float | None = None
    peak_time_s: float | None = None
    dynamic_range_db: float | None = None
    silence_regions: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class AudioObservation:
    """Everything the analysers assert about one audio file, keyed on its bytes.

    Two fields carry the failure modes rather than hiding them, because a silent partial
    answer is worse than a loud one (rule 4 of the repo, applied to a new layer):

      * `partial` -- the worker said so itself: a backend crashed, a stage was skipped, and
        what arrived is a subset. The fallback router treats it as a reason to call Omni.
      * `fallback_used` -- the semantic fields were touched by the free-form model. Recorded
        so provenance can say which sentences in the IR trace to a deterministic analyser and
        which trace to a fallback that was allowed to supplement but not to overwrite.
    """

    sha256: str
    signal: AudioSignalFacts
    speech: list[TimedSpeech] = field(default_factory=list)
    events: list[AudioEvent] = field(default_factory=list)
    voice: AudioVoiceProfile = field(default_factory=AudioVoiceProfile)
    music: AudioMusicProfile = field(default_factory=AudioMusicProfile)
    rhythm: AudioRhythm = field(default_factory=AudioRhythm)

    # The fallback's channel. Supplement only: it may describe, it may never restate or
    # contradict the deterministic fields above (merge policy tier 3, validator rule A26).
    semantic_summary: str = ""
    semantic_facts: list[str] = field(default_factory=list)

    analyzer_version: str = AUDIO_ANALYZER_VERSION
    # Which models produced this, e.g. {"sensevoice": "...", "cam++": "...", "clap": "..."}.
    # Part of provenance, and part of what a cache key must reflect.
    model_ids: dict[str, str] = field(default_factory=dict)
    confidence: float | None = None
    fallback_used: bool = False
    # The worker flagged its own response as incomplete. Never synthesised locally: a worker
    # that cannot say it failed is a worker whose partial answers look complete.
    partial: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> AudioObservation:
        """Rebuild from JSON. Explicit rather than `**raw`: nested dataclasses arrive as plain
        dicts and silence regions arrive as lists, and a constructor that does not convert them
        back produces an object that serialises differently from the one that was saved -- which
        is a cache entry whose hash changes when it is merely reloaded."""
        raw = dict(raw)
        raw["signal"] = AudioSignalFacts(**{
            **raw.get("signal", {}),
            "silence_regions": [tuple(r) for r in raw.get("signal", {}).get("silence_regions", [])],
        })
        raw["speech"] = [TimedSpeech(**s) for s in raw.get("speech", [])]
        raw["events"] = [AudioEvent(**e) for e in raw.get("events", [])]
        raw["voice"] = AudioVoiceProfile(**raw.get("voice", {}))
        raw["music"] = AudioMusicProfile(**raw.get("music", {}))
        raw["rhythm"] = AudioRhythm(**raw.get("rhythm", {}))
        return cls(**raw)

    def hash(self) -> str:
        """Content identity of the observation itself, for provenance ("which observation did
        this IR sentence come from"). Not the cache key -- the cache key is the bytes plus the
        versions, and lives in audio/cache.py."""
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, default=str,
                       ensure_ascii=False).encode()).hexdigest()[:16]
